// Collector-specific entry point for the pinned Iris source. No upstream Main is started.
package party.qwer.iris

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.os.Build
import android.system.Os
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.ApplicationCall
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.server.response.respondText
import io.ktor.server.request.receiveText
import io.ktor.server.routing.get
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File

object CollectorMain {
    private const val HOME = "/data/kakaotalk-bridge"
    private const val ENROLLMENT = "$HOME/enrollment.json"
    private const val AUTH = "$HOME/iris-auth.json"
    private const val KAKAO = "/data/user/0/com.kakao.talk"
    private const val DB = "$KAKAO/databases/KakaoTalk.db"
    private const val PROFILE_DB = "$KAKAO/databases/KakaoTalk2.db"
    private const val ACCOUNT = "$KAKAO/files/datastore/LocalUser_DataStore.pref.preferences_pb"
    private const val BUILD = "iris-ee1dc978-collector-v5"
    private const val PAGE_ROWS = 200
    private const val PAGE_CHARS = 2 * 1024 * 1024
    private val readOnlyErrorHandler = android.database.DatabaseErrorHandler { throw IllegalStateException("source_database_unavailable") }

    private class Unreadable(val reason: String) : Exception()

    private suspend fun authorize(call: ApplicationCall): String? {
        val credentials = runCatching {
            val file = File(AUTH)
            require(file.length() in 1L..4096L)
            val record = JSONObject(file.readText())
            require(CollectorAuth.accepts(call.request.headers["Authorization"], record.getString("token")))
            record.getString("enrollment_epoch")
        }.getOrNull()
        if (credentials == null) {
            call.respondText("{\"error\":\"unauthorized\"}", ContentType.Application.Json, HttpStatusCode.Unauthorized)
        }
        return credentials
    }

    private fun accountIds(): List<Long> = runCatching {
        val file = File(ACCOUNT)
        require(file.length() in 1L..4L * 1024 * 1024)
        ProfileData.accountIds(file.readBytes())
    }.getOrDefault(emptyList())

    /** Approval holds while the operator-confirmed account is signed in on this Android build. */
    private fun approved(): JSONObject {
        val config = JSONObject(File(ENROLLMENT).readText())
        val user = config.optString("approved_user_id")
        require(Regex("[1-9][0-9]{0,18}").matches(user))
        require(config.optString("device_fingerprint") == Build.FINGERPRINT)
        require(config.optString("phone_session_report") != "lost")
        val ids = accountIds().distinct()
        require(ids.size == 1 && ids[0].toString() == user)
        return config
    }

    private fun hasTable(db: SQLiteDatabase, table: String): Boolean = db.rawQuery(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", arrayOf(table)
    ).use { it.moveToFirst() }

    private fun label(name: String?, source: String, reason: String = "record_missing"): JSONObject {
        if (name != null && name.any { Character.isISOControl(it) || it == '\uFFFD' })
            return JSONObject().put("name",JSONObject.NULL).put("status","unavailable")
                .put("reason","invalid_display_name").put("name_source",JSONObject.NULL)
        var end = minOf(name?.length ?: 0,512)
        if (name != null && end < name.length && end > 0 && Character.isHighSurrogate(name[end-1])) end--
        val clean = name?.substring(0,end)?.trim()?.takeIf { it.isNotEmpty() }
        return JSONObject().put("name", clean ?: JSONObject.NULL)
            .put("status", if (clean != null) "resolved" else "not_found")
            .put("reason", if (clean != null) JSONObject.NULL else reason)
            .put("name_source", if (clean != null) source else JSONObject.NULL)
    }

    private fun unavailable(reason: String): JSONObject = label(null, "", reason).put("status", "unavailable")

    private fun userLabel(db: SQLiteDatabase?, link: String?, user: String, own: Long?, crypto: CryptoProfiles?, chat: String, kind: String?): JSONObject {
        if (own != null && user == own.toString()) return label("나", "self")
        val open = !link.isNullOrEmpty() && link != "0"
        if (!open && crypto != null) {
            val name = if (kind == "PlusChat") crypto.channel(user,chat) else crypto.user(user)
            return if (name == null) label(null,"","crypto_profile_record_missing") else label(name.value,name.source)
        }
        if (db == null) return unavailable("profile_database_unavailable")
        if (own == null) return unavailable("self_identity_unavailable")
        val table = if (open) "open_chat_member" else "friends"
        if (!hasTable(db, table)) return unavailable(if (open) "profile_table_missing" else "encrypted_profile_unavailable")
        val sql = if (open) "SELECT nickname,enc FROM open_chat_member WHERE link_id=? AND user_id=? ORDER BY _id DESC LIMIT 1"
                  else "SELECT name,enc FROM friends WHERE id=? LIMIT 1"
        val args = if (open) arrayOf(link!!,user) else arrayOf(user)
        return try {
            db.rawQuery(sql,args).use { c ->
                if (!c.moveToFirst()) label(null,"", "profile_record_missing") else {
                    val encrypted = c.getString(0) ?: ""
                    val decoded = KakaoDecrypt.decrypt(c.getInt(1),encrypted,own)
                    if (decoded == encrypted) unavailable("name_decryption_failed")
                    else label(decoded,if (open) "open_chat_member" else "friends")
                }
            }
        } catch (_: Exception) { unavailable("name_lookup_failed") }
    }

    /** null when no encrypted profile name exists to test an ID against. */
    private fun decrypts(profiles: SQLiteDatabase, user: Long): Boolean? {
        if (!hasTable(profiles, "open_chat_member")) return null
        var tested = 0
        profiles.rawQuery(
            "SELECT nickname,enc FROM open_chat_member WHERE enc>0 AND nickname IS NOT NULL AND nickname<>'' LIMIT 3", null
        ).use { c ->
            while (c.moveToNext()) {
                tested++
                val encrypted = c.getString(0)
                val decoded = runCatching { KakaoDecrypt.decrypt(c.getInt(1), encrypted, user) }.getOrNull()
                if (decoded != null && decoded != encrypted && decoded.none { Character.isISOControl(it) || it == '\uFFFD' }) return true
            }
        }
        return if (tested == 0) null else false
    }

    /** The signed-in user's ID and its source. The stored ID is checked against an encrypted name when one exists. */
    private fun ownUserId(db: SQLiteDatabase, profiles: SQLiteDatabase?): Pair<Long?, String> {
        val stored = accountIds().distinct().singleOrNull()
        if (stored != null && (profiles == null || decrypts(profiles, stored) != false)) return stored to "local_account"
        val sent = db.rawQuery("SELECT user_id FROM chat_logs WHERE v LIKE ? ORDER BY _id DESC LIMIT 1", arrayOf("%\"isMine\":true%")).use {
            if (it.moveToFirst()) it.getLong(0) else null
        }
        return sent to (if (sent != null) "sent_message" else "unavailable")
    }

    private fun row(cursor: Cursor): JSONObject {
        val metadata = try { JSONObject(cursor.getString(6) ?: throw Unreadable("metadata_unreadable")) }
            catch (_: JSONException) { throw Unreadable("metadata_unreadable") }
        val ciphertext = cursor.getString(3) ?: ""
        val placeholder = ciphertext.isEmpty() || ciphertext == "{}" || ciphertext == "[]"
        val enc = metadata.optInt("enc", -1)
        if (!placeholder && enc < 0) throw Unreadable("metadata_unreadable")
        val message = if (placeholder) ciphertext else
            try { KakaoDecrypt.decrypt(enc, ciphertext, cursor.getLong(2)) } catch (_: Exception) { throw Unreadable("decrypt_failed") }
        // Never silently present undeciphered ciphertext as a message.
        if (!placeholder && message == ciphertext) throw Unreadable("decrypt_failed")
        var end = minOf(message.length, 16384)
        if (end < message.length && end > 0 && Character.isHighSurrogate(message[end - 1])) end--
        return JSONObject()
            .put("log_id", cursor.getString(0))
            .put("chat_id", cursor.getString(1))
            .put("sender_id", cursor.getString(2))
            .put("message", message.substring(0, end))
            .put("message_type", cursor.getString(4))
            .put("created_at", cursor.getLong(5))
            .put("origin", metadata.optString("origin", ""))
            .put("is_mine", metadata.optBoolean("isMine", false))
            .put("truncated", end < message.length)
    }

    /** A row that cannot be decoded keeps its position so later rows are not held back. */
    private fun skipped(cursor: Cursor, reason: String): JSONObject = JSONObject()
        .put("log_id", cursor.getString(0))
        .put("chat_id", if (cursor.isNull(1)) "0" else cursor.getString(1))
        .put("sender_id", if (cursor.isNull(2)) "0" else cursor.getString(2))
        .put("message_type", if (cursor.isNull(4)) "" else cursor.getString(4))
        .put("created_at", if (cursor.isNull(5)) 0L else cursor.getLong(5))
        .put("skipped", reason)

    private fun metadata(db: SQLiteDatabase, profiles: SQLiteDatabase?, crypto: CryptoProfiles?, chat: String, user: String, own: Long?): JSONObject {
        var kind: String? = null
        var room = label(null,"", "room_record_missing")
        var sender = label(null,"", "room_record_missing")
        db.rawQuery("SELECT type,link_id,private_meta,members FROM chat_rooms WHERE id=?",arrayOf(chat)).use { c ->
            if (c.moveToFirst()) {
                kind = c.getString(0)
                val link = c.getString(1)
                sender = userLabel(profiles,link,user,own,crypto,chat,kind)
                val custom = runCatching { JSONObject(c.getString(2) ?: "{}").optString("name", "") }.getOrDefault("")
                room = label(custom,"custom_room")
                if (custom.isBlank() && profiles != null && !link.isNullOrEmpty() && link != "0" && hasTable(profiles,"open_link")) {
                    profiles.rawQuery("SELECT name FROM open_link WHERE id=? LIMIT 1",arrayOf(link)).use { r ->
                        room = if (r.moveToFirst()) label(r.getString(0),"open_link") else label(null,"","open_room_record_missing")
                    }
                }
                if (room.optString("status") != "resolved" && kind == "MemoChat") room = label("나와의 채팅","self_chat")
                if (room.optString("status") != "resolved" && kind == "PlusChat" && crypto != null) {
                    val knownUsers = mutableSetOf<String>()
                    val members = runCatching { JSONArray(c.getString(3) ?: "[]") }.getOrDefault(JSONArray())
                    for (i in 0 until minOf(members.length(),100)) knownUsers.add(members.optString(i))
                    db.rawQuery("SELECT DISTINCT user_id FROM chat_logs WHERE chat_id=? LIMIT 100",arrayOf(chat)).use { users ->
                        while (users.moveToNext()) knownUsers.add(users.getString(0))
                    }
                    val name = crypto.channelRoom(chat,knownUsers)
                    room = if (name == null) label(null,"","channel_identity_unresolved") else label(name.value,name.source)
                }
                if (room.optString("status") != "resolved" && (kind == "DirectChat" || kind == "MultiChat")) {
                    val members = runCatching { JSONArray(c.getString(3) ?: "[]") }.getOrDefault(JSONArray())
                    val names = mutableListOf<String>()
                    var complete = members.length() <= 100 && own != null
                    for (i in 0 until minOf(members.length(),100)) {
                        val id = members.optString(i)
                        if (id == own?.toString()) continue
                        val member = userLabel(profiles,null,id,own,crypto,chat,kind)
                        if (member.optString("status") == "resolved") names.add(member.getString("name")) else complete = false
                    }
                    room = if (complete && names.isNotEmpty()) label(names.joinToString(", "),"members")
                           else label(null,"","member_names_unavailable")
                }
            }
        }
        return JSONObject().put("chat_id",chat).put("user_id",user).put("kind",kind ?: JSONObject.NULL)
            .put("sender",sender).put("conversation",room)
    }

    @JvmStatic fun main(args: Array<String>) {
        // ADB forward is the only intended access path. No /reply, /aot, or arbitrary SQL route.
        embeddedServer(Netty, host = "127.0.0.1", port = 3000) {
            routing {
                get("/collector/health") {
                    val result = JSONObject().put("build", BUILD)
                    val challenge = call.request.queryParameters["challenge"]
                    if (challenge != null) {
                        val proof = runCatching {
                            val credentials = JSONObject(File(AUTH).readText())
                            CollectorAuth.proof(challenge, credentials.getString("token"), BUILD)
                        }.getOrNull()
                        if (proof == null) {
                            call.respondText("{\"error\":\"unavailable\"}", ContentType.Application.Json, HttpStatusCode.ServiceUnavailable)
                            return@get
                        }
                        result.put("proof", proof)
                    }
                    call.respondText(result.toString(), ContentType.Application.Json)
                }
                post("/collector/metadata") {
                    val epoch = authorize(call) ?: return@post
                    try {
                        val config = approved()
                        require(config.getString("enrollment_epoch") == epoch)
                        require((call.request.headers["Content-Length"]?.toLongOrNull() ?: 0L) in 1L..32768L)
                        val targets = JSONObject(call.receiveText()).getJSONArray("targets")
                        require(targets.length() in 1..50)
                        val stat = Os.stat(DB)
                        val rows = JSONArray()
                        var selfSource = "unavailable"
                        SQLiteDatabase.openDatabase(DB,null,SQLiteDatabase.OPEN_READONLY,readOnlyErrorHandler).use { db ->
                            val profiles = runCatching { SQLiteDatabase.openDatabase(PROFILE_DB,null,SQLiteDatabase.OPEN_READONLY,readOnlyErrorHandler) }.getOrNull()
                            val crypto = runCatching { CryptoProfiles.open() }.getOrNull()
                            try {
                                val (own, source) = ownUserId(db, profiles)
                                selfSource = source
                                for (i in 0 until targets.length()) {
                                    val t = targets.getJSONObject(i)
                                    val chat = t.getString("chat_id"); val user = t.getString("user_id")
                                    require(Regex("-?[0-9]{1,20}").matches(chat) && Regex("-?[0-9]{1,20}").matches(user))
                                    val result = try { metadata(db,profiles,crypto,chat,user,own) } catch (_: Exception) {
                                        JSONObject().put("chat_id",chat).put("user_id",user).put("kind",JSONObject.NULL)
                                            .put("sender",unavailable("metadata_lookup_failed"))
                                            .put("conversation",unavailable("metadata_lookup_failed"))
                                    }
                                    rows.put(result)
                                }
                            } finally { try { crypto?.close() } finally { profiles?.close() } }
                        }
                        require(approved().toString() == config.toString())
                        call.respondText(JSONObject().put("build",BUILD).put("enrollment_epoch",config.getString("enrollment_epoch"))
                            .put("database_id","${stat.st_dev}:${stat.st_ino}").put("self_identity_source",selfSource)
                            .put("items",rows).toString(),ContentType.Application.Json)
                    } catch (_: Exception) {
                        call.respondText("{\"error\":\"metadata_unavailable\"}",ContentType.Application.Json,HttpStatusCode.ServiceUnavailable)
                    }
                }
                get("/collector/rows") {
                    val epoch = authorize(call) ?: return@get
                    try {
                        synchronized(CollectorMain) {
                            val config = approved()
                            require(config.getString("enrollment_epoch") == epoch)
                            val after = call.request.queryParameters["after"]?.toLongOrNull() ?: 0L
                            require(after >= 0)
                            val stat = Os.stat(DB)
                            // Open per page so Android restarts / WAL changes do not leave a stale handle.
                            SQLiteDatabase.openDatabase(DB, null, SQLiteDatabase.OPEN_READONLY,readOnlyErrorHandler).use { db ->
                                val high = db.rawQuery("SELECT COALESCE(MAX(_id),0) FROM chat_logs", null).use {
                                    it.moveToFirst(); it.getLong(0)
                                }
                                val rows = JSONArray()
                                var size = 0
                                var more = false
                                db.rawQuery(
                                    "SELECT _id,chat_id,user_id,message,type,created_at,v FROM chat_logs WHERE _id>? ORDER BY _id ASC LIMIT ?",
                                    arrayOf(after.toString(), (PAGE_ROWS + 1).toString())
                                ).use { cursor ->
                                    while (cursor.moveToNext()) {
                                        if (rows.length() == PAGE_ROWS) { more = true; break }
                                        val item = try { row(cursor) }
                                            catch (e: Unreadable) { skipped(cursor, e.reason) }
                                            catch (_: Exception) { skipped(cursor, "unreadable") }
                                        val text = item.toString()
                                        if (rows.length() > 0 && size + text.length > PAGE_CHARS) { more = true; break }
                                        size += text.length
                                        rows.put(item)
                                    }
                                }
                                // Recheck revocation / account change before releasing the page.
                                require(approved().toString() == config.toString())
                                val result = JSONObject().put("build", BUILD)
                                    .put("enrollment_epoch", config.getString("enrollment_epoch"))
                                    .put("database_id", "${stat.st_dev}:${stat.st_ino}")
                                    .put("high_water", high.toString()).put("has_more", more).put("rows", rows)
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
