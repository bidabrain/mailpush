package com.melonmail.app.push

import android.app.PendingIntent
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.melonmail.app.CHANNEL_MAIL
import com.melonmail.app.MainActivity
import com.melonmail.app.R
import com.melonmail.app.data.Settings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicInteger

/**
 * 收 server 发来的 data message(字段 sender/subject/account),自行弹通知。
 * 用 data message + priority high(服务端已设),保证后台可靠唤醒。
 */
class MelonMessagingService : FirebaseMessagingService() {

    private val ioScope = CoroutineScope(Dispatchers.IO)

    override fun onNewToken(token: String) {
        // token 会轮换:存本地,设置页展示(单设备先手动同步到服务器 device-token)。
        ioScope.launch { Settings(applicationContext).setFcmToken(token) }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val sender = data["sender"].orEmpty()
        val subject = data["subject"].orEmpty().ifBlank { "(新邮件)" }
        val account = data["account"].orEmpty()
        val id = data["id"].orEmpty()
        showNotification(sender, subject, account, id)
    }

    private fun showNotification(sender: String, subject: String, account: String, id: String) {
        val title = buildString {
            append(sender.ifBlank { "新邮件" })
            if (account.isNotBlank()) append(" · ").append(account)
        }

        val notifId = nextId()
        val intent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            if (account.isNotBlank()) putExtra(EXTRA_ACCOUNT, account)
            if (id.isNotBlank()) putExtra(EXTRA_ID, id)
        }
        // 每条通知用不同 requestCode,避免 PendingIntent 复用导致 extras 串台。
        val pending = PendingIntent.getActivity(
            this,
            notifId,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_MAIL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(subject)
            .setStyle(NotificationCompat.BigTextStyle().bigText(subject))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()

        // 无通知权限(Android 13+ 未授予)时 notify 静默失败,catch 兜底。
        try {
            NotificationManagerCompat.from(this).notify(notifId, notification)
        } catch (_: SecurityException) {
        }
    }

    companion object {
        const val EXTRA_ACCOUNT = "account"
        const val EXTRA_ID = "id"
        private val counter = AtomicInteger(1)
        private fun nextId() = counter.getAndIncrement()
    }
}
