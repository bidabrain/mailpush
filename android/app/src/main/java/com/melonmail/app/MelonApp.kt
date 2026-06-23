package com.melonmail.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import com.google.firebase.messaging.FirebaseMessaging
import com.melonmail.app.data.Api
import com.melonmail.app.data.MailCache
import com.melonmail.app.data.PinStore
import com.melonmail.app.data.Settings
import com.melonmail.app.data.TokenRegister
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import java.io.File

const val CHANNEL_MAIL = "mail"

class MelonApp : Application() {

    lateinit var settings: Settings
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    // 避免重复上报:记录上次成功注册的 (baseUrl|apiToken|fcmToken) 组合。
    @Volatile private var lastRegisterKey: String? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        settings = Settings(this)
        createMailChannel()

        // baseUrl/apiToken/fcmToken 任一变化:重建 API 客户端,并(齐全时)自动把本机
        // FCM token 上报到服务器(多设备,服务端去重)。彻底免去手动填 device-token。
        scope.launch {
            combine(settings.baseUrl, settings.apiToken, settings.fcmToken) { b, a, f ->
                Triple(b, a, f)
            }.collect { (baseUrl, apiToken, fcmToken) ->
                Api.update(baseUrl, apiToken)
                if (baseUrl.isNotBlank() && apiToken.isNotBlank() && fcmToken.isNotBlank()) {
                    val key = "$baseUrl|$apiToken|$fcmToken"
                    if (key != lastRegisterKey) {
                        runCatching { Api.service?.registerToken(TokenRegister(fcmToken)) }
                            .onSuccess { lastRegisterKey = key }
                    }
                }
            }
        }

        // 启动清理缓存:附件(>7 天)+ 正文缓存(超 16MB 删最旧,置顶豁免)。
        scope.launch {
            pruneAttachmentCache()
            val pinned = PinStore(this@MelonApp).load().map { it.account to it.envelope.id }
            MailCache(this@MelonApp).pruneMessages(MailCache.MAX_MESSAGE_CACHE_BYTES, pinned)
        }

        // 取当前 FCM token 存本地(设置页展示 + 触发上述自动上报)。
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (task.isSuccessful) {
                val token = task.result
                scope.launch { settings.setFcmToken(token) }
            }
        }
    }

    private fun pruneAttachmentCache() {
        val dir = File(cacheDir, "attachments")
        val cutoff = System.currentTimeMillis() - 7L * 24 * 3600 * 1000
        dir.listFiles()?.forEach { if (it.isFile && it.lastModified() < cutoff) it.delete() }
    }

    private fun createMailChannel() {
        val mgr = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_MAIL,
            getString(R.string.notification_channel_mail),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = getString(R.string.notification_channel_mail_desc)
        }
        mgr.createNotificationChannel(channel)
    }

    companion object {
        lateinit var instance: MelonApp
            private set
    }
}
