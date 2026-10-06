// Kakao notification reply protocol follows the pinned Iris Replier (GPL-3.0).
// See NOTICE.md. No upstream conflated queue, mutable config, or body logging.
package party.qwer.iris

import android.app.RemoteInput
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.os.IBinder
import android.util.Xml
import org.xmlpull.v1.XmlPullParser
import java.io.File

object CollectorSender {
    private const val SERVICE = "com.kakao.talk.notification.NotificationActionService"

    fun prepare(chat: Long, text: String): Intent {
        require(chat > 0 && text.isNotBlank() && text.length <= 4000 && !text.contains('\u0000'))
        val file = File("/data/user/0/com.kakao.talk/shared_prefs/KakaoTalk.hw.perferences.xml")
        require(file.length() in 1L..1048576L)
        val referer = file.inputStream().use { input ->
            val parser = Xml.newPullParser()
            parser.setInput(input, "UTF-8")
            var value: String? = null
            while (parser.next() != XmlPullParser.END_DOCUMENT) {
                if (parser.eventType == XmlPullParser.START_TAG && parser.name == "string"
                    && parser.getAttributeValue(null, "name") == "NotificationReferer") {
                    value = parser.nextText()
                    break
                }
            }
            require(!value.isNullOrBlank())
            value
        }
        return Intent("com.kakao.talk.notification.REPLY_MESSAGE").apply {
            component = ComponentName("com.kakao.talk", SERVICE)
            putExtra("noti_referer", referer)
            putExtra("chat_id", chat)
            putExtra("is_chat_thread_notification", false)
            RemoteInput.addResultsToIntent(arrayOf(RemoteInput.Builder("reply_message").build()),
                this, Bundle().apply { putCharSequence("reply_message", text) })
        }
    }

    fun submit(intent: Intent) {
        // Android 14 redroid: inspect the returned component instead of discarding errors.
        val binder = Class.forName("android.os.ServiceManager")
            .getMethod("getService", String::class.java).invoke(null, "activity")
        val manager = Class.forName("android.app.IActivityManager\$Stub")
            .getMethod("asInterface", IBinder::class.java).invoke(null, binder)
        val method = Class.forName("android.app.IActivityManager").getMethod("startService",
            Class.forName("android.app.IApplicationThread"), Intent::class.java,
            String::class.java, Boolean::class.javaPrimitiveType, String::class.java,
            String::class.java, Int::class.javaPrimitiveType)
        val component = method.invoke(manager, null, intent, null, false,
            "com.android.shell", null, 0) as? ComponentName
        require(component?.packageName == "com.kakao.talk" && component.className == SERVICE)
    }
}
