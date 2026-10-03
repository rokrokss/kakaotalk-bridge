// Collector-specific entry point for the pinned Iris source. No upstream Main is started.
package party.qwer.iris

import android.database.sqlite.SQLiteDatabase
import android.os.Build
import android.system.Os
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object CollectorMain {
    private const val CONFIG = "/data/user/0/dev.kakaocollector.bridge/files/enrollment.json"
    private const val DB = "/data/user/0/com.kakao.talk/databases/KakaoTalk.db"
    private const val BUILD = "iris-ee1dc978-collector-v1"

    private fun enrolled(): JSONObject {
        val config = JSONObject(File(CONFIG).readText())
        require(config.optString("collector_mode") == "iris")
        require(config.getLong("secondary_login_version") > 0)
        require(config.getString("device_fingerprint") == Build.FINGERPRINT)
        val process = ProcessBuilder("/system/bin/dumpsys", "package", "com.kakao.talk").start()
        val info = process.inputStream.bufferedReader().use { it.readText() }
        require(process.waitFor() == 0)
        val version = Regex("versionCode=(\\d+)").find(info)?.groupValues?.get(1)?.toLong()
        require(version == config.getLong("secondary_login_version"))
        return config
    }

    @JvmStatic fun main(args: Array<String>) {
        // ADB forward is the only intended access path. No /reply, /aot, or arbitrary SQL route.
        embeddedServer(Netty, host = "127.0.0.1", port = 3000) {
            routing {
                get("/collector/health") {
                    call.respondText(JSONObject().put("build", BUILD).toString(), ContentType.Application.Json)
                }
                get("/collector/rows") {
                    try {
                        synchronized(CollectorMain) {
                            val config = enrolled()
                            val after = call.request.queryParameters["after"]?.toLongOrNull() ?: 0L
                            require(after >= 0)
                            val stat = Os.stat(DB)
                            // Open per page so Android restarts / WAL changes do not leave a stale handle.
                            SQLiteDatabase.openDatabase(DB, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                                val high = db.rawQuery("SELECT COALESCE(MAX(_id),0) FROM chat_logs", null).use {
                                    it.moveToFirst(); it.getLong(0)
                                }
                                val rows = JSONArray()
                                db.rawQuery(
                                    "SELECT _id,chat_id,user_id,message,type,created_at,v FROM chat_logs WHERE _id>? ORDER BY _id ASC LIMIT 50",
                                    arrayOf(after.toString())
                                ).use { cursor ->
                                    while (cursor.moveToNext()) {
                                        val metadata = JSONObject(cursor.getString(6))
                                        val ciphertext = cursor.getString(3) ?: ""
                                        val placeholder = ciphertext.isEmpty() || ciphertext == "{}" || ciphertext == "[]"
                                        val message = if (placeholder) ciphertext else
                                            KakaoDecrypt.decrypt(metadata.getInt("enc"), ciphertext, cursor.getLong(2))
                                        // Never silently present undeciphered ciphertext as a message.
                                        require(placeholder || message != ciphertext)
                                        var end = minOf(message.length, 16384)
                                        if (end < message.length && end > 0 && Character.isHighSurrogate(message[end - 1])) end--
                                        rows.put(JSONObject()
                                            .put("log_id", cursor.getString(0))
                                            .put("chat_id", cursor.getString(1))
                                            .put("sender_id", cursor.getString(2))
                                            .put("message", message.substring(0, end))
                                            .put("message_type", cursor.getString(4))
                                            .put("created_at", cursor.getLong(5))
                                            .put("origin", metadata.optString("origin", ""))
                                            .put("is_mine", metadata.optBoolean("isMine", false))
                                            .put("truncated", end < message.length))
                                    }
                                }
                                // Recheck revocation / APK change before releasing the page.
                                require(enrolled().toString() == config.toString())
                                val result = JSONObject().put("build", BUILD)
                                    .put("enrollment_epoch", config.getString("enrollment_epoch"))
                                    .put("database_id", "${stat.st_dev}:${stat.st_ino}")
                                    .put("high_water", high.toString()).put("rows", rows)
                                // respondText is suspending: return serialized data from the lock first.
                                result.toString()
                            }
                        }.let { call.respondText(it, ContentType.Application.Json) }
                    } catch (_: Exception) {
                        // No SQL, credentials, message bodies or stack traces in logs/responses.
                        call.respondText("{\"error\":\"iris_locked_or_database_unavailable\"}",
                            ContentType.Application.Json, HttpStatusCode.ServiceUnavailable)
                    }
                }
            }
        }.start(wait = true)
    }
}
