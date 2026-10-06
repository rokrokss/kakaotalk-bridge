package dev.kakaotalkbridge.android

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

/** Launcher screen. The app only provides the admin screen's keyboard. */
class SetupActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply {
            text = "KakaoTalk Bridge 키보드\n\n관리 화면에서 보낸 텍스트를 카카오톡 입력란에 입력합니다. " +
                "메시지를 읽거나 보내지 않으며, 입력한 내용은 저장하지 않습니다."
            setPadding(32, 48, 32, 32)
        })
    }
}
