package dev.kakaocollector.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.inputmethodservice.InputMethodService
import android.view.View
import android.widget.TextView
import org.json.JSONObject
import java.io.File
import androidx.core.content.ContextCompat

/** Explicit web input only. Never reads surrounding text, records keys, or submits a form. */
class WebInputMethod : InputMethodService() {
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action != "dev.kakaocollector.bridge.WEB_TEXT") return
            val pending = File(filesDir, "web-input.json")
            try {
                val data = JSONObject(pending.readText())
                pending.delete()
                val nonce = data.getString("nonce")
                require(nonce.matches(Regex("[a-f0-9]{32}")))
                val text = data.getString("text")
                require(text.length <= 4096)
                val connected = currentInputConnection
                val allowed = currentInputEditorInfo?.packageName == "com.kakao.talk"
                val committed = allowed && connected != null && connected.commitText(text, 1)
                File(filesDir, "web-input-result.json").writeText(
                    JSONObject().put("nonce", nonce).put("committed", committed).toString()
                )
            } catch (_: Exception) {
                // Never put typed content, credentials, or exceptions in logcat.
            } finally { pending.delete() }
        }
    }

    override fun onCreate() {
        super.onCreate()
        File(filesDir, "web-input.json").delete()
        val filter = IntentFilter("dev.kakaocollector.bridge.WEB_TEXT")
        // Only shell/root or another holder of the system DUMP permission may trigger input.
        ContextCompat.registerReceiver(this, receiver, filter, "android.permission.DUMP", null,
            ContextCompat.RECEIVER_EXPORTED)
    }

    override fun onCreateInputView(): View = TextView(this).apply {
        text = "Enter text in the web admin console · Input is not stored"
        setPadding(16, 16, 16, 16)
    }
    override fun onEvaluateFullscreenMode(): Boolean = false
    override fun onDestroy() {
        unregisterReceiver(receiver)
        File(filesDir, "web-input.json").delete()
        File(filesDir, "web-input-result.json").delete()
        super.onDestroy()
    }
}
