package com.melonmail.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableStateOf
import com.melonmail.app.push.MelonMessagingService
import com.melonmail.app.ui.AppRoot
import com.melonmail.app.ui.theme.MelonTheme

/** 通知点击的跳转目标(账号 + 可选邮件 id)。 */
data class NavTarget(val account: String, val messageId: String?)

class MainActivity : ComponentActivity() {

    // Compose 观察:onCreate(冷启动)与 onNewIntent(应用在后台)都写它,AppRoot 据此跳转。
    private val navTarget = mutableStateOf<NavTarget?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleIntent(intent)
        setContent {
            MelonTheme {
                AppRoot(navTarget)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val account = intent?.getStringExtra(MelonMessagingService.EXTRA_ACCOUNT)
        if (!account.isNullOrBlank()) {
            navTarget.value = NavTarget(account, intent.getStringExtra(MelonMessagingService.EXTRA_ID))
        }
    }
}
