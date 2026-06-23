package com.melonmail.app.data

import android.content.Context
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 简易离线缓存(JSON 文件,存 filesDir/mailcache)。
 * 账号列表 / 各账号收件箱(最新一页)/ 已打开的正文。没网时回退显示这些。
 */
class MailCache(context: Context) {

    private val dir = File(context.filesDir, "mailcache").apply { mkdirs() }
    private val json = Json { ignoreUnknownKeys = true }

    private fun safe(s: String) = s.replace(Regex("[^A-Za-z0-9._-]"), "_")

    fun saveAccounts(list: List<String>) {
        runCatching { File(dir, "accounts.json").writeText(json.encodeToString(list)) }
    }

    fun loadAccounts(): List<String> =
        runCatching { json.decodeFromString<List<String>>(File(dir, "accounts.json").readText()) }
            .getOrDefault(emptyList())

    // 按 账号+文件夹 分别缓存,避免「收件箱」和「已发」互相覆盖。
    fun saveInbox(account: String, folder: String, list: List<Envelope>) {
        runCatching { File(dir, "inbox-${safe(account)}-${safe(folder)}.json").writeText(json.encodeToString(list)) }
    }

    fun loadInbox(account: String, folder: String): List<Envelope> =
        runCatching { json.decodeFromString<List<Envelope>>(File(dir, "inbox-${safe(account)}-${safe(folder)}.json").readText()) }
            .getOrDefault(emptyList())

    fun saveMessage(account: String, id: String, body: MsgBody) {
        runCatching { File(dir, "msg-${safe(account)}-${safe(id)}.json").writeText(json.encodeToString(body)) }
    }

    fun loadMessage(account: String, id: String): MsgBody? =
        runCatching { json.decodeFromString<MsgBody>(File(dir, "msg-${safe(account)}-${safe(id)}.json").readText()) }
            .getOrNull()

    /**
     * 回收正文缓存:按文件最近写入(≈最近一次联网打开)从新到旧保留,累计大小超过
     * [maxBytes] 后,把更旧的删掉。置顶邮件([pinned] = (account,id) 列表)永远保留、不删。
     * 只动 msg-*.json,不碰列表/账号/置顶缓存。
     */
    fun pruneMessages(maxBytes: Long, pinned: List<Pair<String, String>>) {
        val exempt = pinned.mapTo(HashSet()) { (acc, id) -> "msg-${safe(acc)}-${safe(id)}.json" }
        val files = (dir.listFiles { f -> f.isFile && f.name.startsWith("msg-") && f.name.endsWith(".json") }
            ?: return).sortedByDescending { it.lastModified() }  // 新 → 旧
        var total = 0L
        for (f in files) {
            total += f.length()
            if (total > maxBytes && f.name !in exempt) {
                runCatching { f.delete() }
            }
        }
    }

    companion object {
        const val MAX_MESSAGE_CACHE_BYTES = 16L * 1024 * 1024  // 正文缓存上限 ~16MB
    }
}
