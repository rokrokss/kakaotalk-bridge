package dev.kakaocollector.bridge

import android.app.Activity
import android.app.Notification
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.work.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory

private const val KAKAO = "com.kakao.talk"
private const val MAX_BYTES = 100L * 1024 * 1024

data class Enrollment(val device: String, val epoch: String, val url: String, val token: String, val ca: String,
                      val secondaryVersion: Long, val fingerprint: String, val mode: String) {
    @Suppress("DEPRECATION")
    fun collectionAllowed(context: Context): Boolean = runCatching {
        mode == "notification" && secondaryVersion > 0 && fingerprint == android.os.Build.FINGERPRINT &&
            context.resources.configuration.smallestScreenWidthDp >= 600 &&
            context.packageManager.getPackageInfo(KAKAO, 0).longVersionCode == secondaryVersion
    }.getOrDefault(false)
    companion object {
        fun load(context: Context): Enrollment? = runCatching {
            val json = JSONObject(File(context.filesDir, "enrollment.json").readText())
            val url = json.getString("url").trimEnd('/')
            require(url.startsWith("https://"))
            require(java.net.URI(url).userInfo == null)
            UUID.fromString(json.getString("enrollment_epoch"))
            Enrollment(json.getString("device_id"), json.getString("enrollment_epoch"), url,
                json.getString("token"), json.getString("ca_pem"),
                json.optLong("secondary_login_version", 0), json.optString("device_fingerprint", ""), json.optString("collector_mode", "notification"))
        }.getOrNull()
    }
}

class Outbox private constructor(context: Context) : SQLiteOpenHelper(context, "outbox.db", null, 1) {
    private val prefs = context.getSharedPreferences("health", Context.MODE_PRIVATE)
    override fun onConfigure(db: SQLiteDatabase) { db.execSQL("PRAGMA secure_delete=ON") }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE queue (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0)")
        db.execSQL("CREATE TABLE meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        db.execSQL("INSERT INTO meta VALUES('last_seq',0)")
        db.execSQL("INSERT INTO meta VALUES('queued_bytes',0)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        error("Unsupported outbox migration; preserve existing database")
    }
    @Synchronized fun dropped() {
        prefs.edit().putLong("dropped", prefs.getLong("dropped", 0) + 1).commit()
    }
    @Synchronized fun enqueue(event: JSONObject) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val size = db.rawQuery("SELECT value FROM meta WHERE key='queued_bytes'", null).use { it.moveToFirst(); it.getLong(0) }
            if (size + event.toString().toByteArray(Charsets.UTF_8).size + 64 > MAX_BYTES) {
                dropped()
                return
            }
            val id = event.getString("event_id")
            val values = ContentValues().apply {
                put("event_id", id); put("body", ""); put("created_at", event.getString("observed_at"))
            }
            val seq = db.insertOrThrow("queue", null, values)
            event.put("source_seq", seq)
            db.execSQL("UPDATE queue SET body=? WHERE seq=?", arrayOf<Any>(event.toString(), seq))
            db.execSQL("UPDATE meta SET value=? WHERE key='last_seq'", arrayOf(seq))
            db.execSQL("UPDATE meta SET value=value+? WHERE key='queued_bytes'",
                arrayOf(event.toString().toByteArray(Charsets.UTF_8).size))
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
    @Synchronized fun first(): Pair<Long, JSONObject>? = readableDatabase.rawQuery(
        "SELECT seq,body FROM queue WHERE quarantined=0 ORDER BY seq LIMIT 1", null
    ).use { if (it.moveToFirst()) it.getLong(0) to JSONObject(it.getString(1)) else null }
    @Synchronized fun ack(seq: Long) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.execSQL("UPDATE meta SET value=value-COALESCE((SELECT length(CAST(body AS BLOB)) FROM queue WHERE seq=?),0) WHERE key='queued_bytes'", arrayOf(seq))
            db.delete("queue", "seq=?", arrayOf(seq.toString()))
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
    @Synchronized fun quarantine(seq: Long) {
        writableDatabase.execSQL("UPDATE queue SET quarantined=1 WHERE seq=?", arrayOf(seq))
    }
    @Synchronized fun heartbeat(enrollment: Enrollment): JSONObject {
        val db = readableDatabase
        val depth = db.rawQuery("SELECT COUNT(*) FROM queue WHERE quarantined=0", null).use { it.moveToFirst(); it.getInt(0) }
        val rejected = db.rawQuery("SELECT COUNT(*) FROM queue WHERE quarantined=1", null).use { it.moveToFirst(); it.getInt(0) }
        val seq = db.rawQuery("SELECT value FROM meta WHERE key='last_seq'", null).use { it.moveToFirst(); it.getLong(0) }
        val oldest = db.rawQuery("SELECT min(created_at) FROM queue WHERE quarantined=0", null).use { it.moveToFirst(); it.getString(0) }
        return JSONObject().put("device_id", enrollment.device).put("enrollment_epoch", enrollment.epoch)
            .put("listener_connected", KakaoListener.connected).put("outbox_depth", depth)
            .put("last_source_seq", seq).put("dropped_events", prefs.getLong("dropped", 0))
            .put("quarantine_depth", rejected).put("oldest_pending_at", oldest ?: JSONObject.NULL)
    }
    companion object {
        @Volatile private var instance: Outbox? = null
        fun get(context: Context): Outbox = instance ?: synchronized(this) {
            instance ?: Outbox(context.applicationContext).also { instance = it }
        }
    }
}

object Delivery {
    fun schedule(context: Context) {
        val work = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS).build()
        WorkManager.getInstance(context).enqueueUniqueWork("upload", ExistingWorkPolicy.KEEP, work)
    }
    fun initialize(context: Context) {
        val periodic = PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("recovery", ExistingPeriodicWorkPolicy.KEEP, periodic)
        schedule(context)
    }
}

class KakaoListener : NotificationListenerService() {
    private val handler = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() { Delivery.schedule(this@KakaoListener); handler.postDelayed(this, 30000) }
    }
    override fun onListenerConnected() {
        connected = true
        Delivery.initialize(this)
        handler.removeCallbacks(tick); handler.post(tick)
        runCatching { activeNotifications?.forEach { observe(it, "snapshot") } }
            .onFailure { Outbox.get(this).dropped() }
    }
    override fun onListenerDisconnected() {
        connected = false
        handler.removeCallbacks(tick)
        Delivery.schedule(this)
        requestRebind(ComponentName(this, KakaoListener::class.java))
    }
    override fun onDestroy() { connected = false; handler.removeCallbacks(tick); super.onDestroy() }
    override fun onNotificationPosted(sbn: StatusBarNotification) { observe(sbn, "posted") }
    override fun onNotificationRemoved(sbn: StatusBarNotification) { observe(sbn, "removed") }
    private fun observe(sbn: StatusBarNotification, kind: String) {
        if (sbn.packageName != KAKAO) return
        val config = Enrollment.load(this) ?: return
        if (!config.collectionAllowed(this)) return
        runCatching {
            val n = sbn.notification
            val extras = n.extras
            var truncated = false
            fun clip(value: CharSequence?, max: Int = 4000): Any {
                if (value == null) return JSONObject.NULL
                if (value.length > max) truncated = true
                val clipped = value.toString().take(max)
                return if (clipped.lastOrNull()?.isHighSurrogate() == true) clipped.dropLast(1) else clipped
            }
            val p = JSONObject().put("is_group_summary", n.flags and Notification.FLAG_GROUP_SUMMARY != 0)
            if (kind != "removed") {
                p.put("title", clip(extras.getCharSequence(Notification.EXTRA_TITLE), 512))
                p.put("text", clip(extras.getCharSequence(Notification.EXTRA_TEXT)))
                p.put("big_text", clip(extras.getCharSequence(Notification.EXTRA_BIG_TEXT)))
                val lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES) ?: emptyArray()
                if (lines.size > 25) truncated = true
                p.put("text_lines", JSONArray().apply { lines.take(25).forEach { put(clip(it)) } })
                @Suppress("DEPRECATION")
                val bundles = extras.getParcelableArray(Notification.EXTRA_MESSAGES)
                val messages: List<Notification.MessagingStyle.Message> = if (bundles == null) emptyList()
                    else Notification.MessagingStyle.Message.getMessagesFromBundleArray(bundles)
                if (messages.size > 25) truncated = true
                p.put("messages", JSONArray().apply {
                    messages.takeLast(25).forEach { message ->
                        put(JSONObject().put("body", clip(message.text ?: ""))
                            .put("sender", clip(message.senderPerson?.name, 512))
                            .put("timestamp", message.timestamp.coerceAtLeast(0)))
                    }
                })
            }
            p.put("truncated", truncated)
            Outbox.get(this).enqueue(JSONObject().put("event_id", UUID.randomUUID().toString())
                .put("device_id", config.device).put("enrollment_epoch", config.epoch)
                .put("source", "notification").put("kind", kind).put("package_name", KAKAO)
                .put("notification_key", sbn.key.take(2048)).put("observed_at", Instant.now().toString())
                .put("notification_posted_at", sbn.postTime.coerceAtLeast(0)).put("payload", p))
            Delivery.schedule(this)
        }.onFailure { Outbox.get(this).dropped() }
    }
    companion object { @Volatile var connected = false }
}

class UploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val config = Enrollment.load(applicationContext) ?: return Result.success()
        if (config.mode == "iris") return Result.success()
        val queue = Outbox.get(applicationContext)
        return try {
            val certificates = CertificateFactory.getInstance("X.509")
                .generateCertificates(config.ca.byteInputStream())
            require(certificates.isNotEmpty())
            val keys = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null); certificates.forEachIndexed { index, cert -> setCertificateEntry("ca-$index", cert) }
            }
            val managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(keys) }
            val tls = SSLContext.getInstance("TLS").apply { init(null, managers.trustManagers, null) }
            fun post(path: String, body: JSONObject): JSONObject {
                val conn = java.net.URL(config.url + path).openConnection() as HttpsURLConnection
                conn.sslSocketFactory = tls.socketFactory
                // Keep the platform hostname verifier; never follow credential-bearing redirects.
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 10000; conn.readTimeout = 15000
                conn.requestMethod = "POST"; conn.doOutput = true
                conn.setRequestProperty("Authorization", "Bearer " + config.token)
                conn.setRequestProperty("Content-Type", "application/json")
                try {
                    conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                    check(conn.responseCode == 200) { "Delivery failed" }
                    return JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                } finally { conn.disconnect() }
            }
            fun heartbeat() = queue.heartbeat(config).put("secondary_login_confirmed", config.collectionAllowed(applicationContext))
            post("/internal/v1/heartbeat", heartbeat())
            if (!config.collectionAllowed(applicationContext)) return Result.success()
            val start = SystemClock.elapsedRealtime()
            var delivered = 0
            while (!isStopped && SystemClock.elapsedRealtime() - start < 180000 && delivered < 100) {
                // Re-read enrollment so a new pre-login check can revoke a running upload.
                if (Enrollment.load(applicationContext)?.collectionAllowed(applicationContext) != true) break
                val (seq, event) = queue.first() ?: break
                val reply = post("/internal/v1/observations:batch",
                    JSONObject().put("schema_version", 1).put("events", JSONArray().put(event)))
                val result = reply.getJSONArray("results").getJSONObject(0)
                check(result.getInt("index") == 0)
                when (result.getString("status")) {
                    "committed", "duplicate" -> {
                        check(result.getString("event_id") == event.getString("event_id"))
                        queue.ack(seq)
                    }
                    "rejected" -> queue.quarantine(seq)
                    else -> error("Unknown acknowledgement")
                }
                delivered++
            }
            val latest = Enrollment.load(applicationContext)
            post("/internal/v1/heartbeat", queue.heartbeat(config).put("secondary_login_confirmed",
                latest?.collectionAllowed(applicationContext) == true))
            if (queue.first() == null) Result.success() else Result.retry()
        } catch (_: Exception) {
            // Never log request payloads, enrollment credentials or response bodies.
            Result.retry()
        }
    }
}

class SetupActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState) }
    override fun onResume() {
        super.onResume()
        val config = Enrollment.load(this)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 48, 32, 32) }
        layout.addView(TextView(this).apply {
            text = if (config == null) "서버에서 bootstrap을 실행한 후 이 앱을 다시 여세요."
                   else if (config.mode == "iris") "redroid 가상 태블릿 · Iris DB 수집 모드\n알림 접근 권한은 필요하지 않습니다.\n서버에서 login-check와 confirm-secondary를 완료한 뒤 수집 상태를 확인하세요.\n핸드폰 로그인 유지 확인은 필수입니다."
                   else if (!config.collectionAllowed(this@SetupActivity)) "수집 잠김: 보조 기기 로그인과 핸드폰 로그인 유지를 먼저 확인하세요.\n로그인 전에 서버의 login-check를 실행하고, 양쪽 세션 확인 후 confirm-secondary로 활성화하세요.\n주 기기 이전 로그인은 진행하지 마세요."
                   else "등록 기기: ${config.device}\n운영자가 양쪽 세션 유지를 확인했습니다. 핸드폰 상태를 자동 감시하는 것은 아닙니다.\n알림만 수집하며 채팅방을 열거나 메시지를 보내지 않습니다."
        })
        layout.addView(Button(this).apply {
            text = "알림 접근 설정"
            setOnClickListener { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        })
        layout.addView(Button(this).apply {
            text = "연결 다시 시도"
            setOnClickListener {
                NotificationListenerService.requestRebind(ComponentName(this@SetupActivity, KakaoListener::class.java))
                Delivery.initialize(this@SetupActivity)
            }
        })
        setContentView(layout)
        if (config != null) {
            Delivery.initialize(this)
            NotificationListenerService.requestRebind(ComponentName(this, KakaoListener::class.java))
        }
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        KakaoListener.connected = false
        Delivery.initialize(context)
        NotificationListenerService.requestRebind(ComponentName(context, KakaoListener::class.java))
    }
}
