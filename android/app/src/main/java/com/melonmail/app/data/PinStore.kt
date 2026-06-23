package com.melonmail.app.data

import android.content.Context
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 置顶邮件的持久化存储(JSON,存 filesDir/pins/pins.json)。
 * 刻意放在 filesDir(不是 cacheDir),不参与 app 的附件缓存自动清理 → pin 内容长期保留,
 * 除非用户 unpin 或邮件在服务器端被删。
 */
class PinStore(context: Context) {

    private val dir = File(context.filesDir, "pins").apply { mkdirs() }
    private val file = File(dir, "pins.json")
    private val json = Json { ignoreUnknownKeys = true }

    fun load(): List<PinnedMail> =
        runCatching { json.decodeFromString<List<PinnedMail>>(file.readText()) }
            .getOrDefault(emptyList())

    fun save(list: List<PinnedMail>) {
        runCatching { file.writeText(json.encodeToString(list)) }
    }
}
