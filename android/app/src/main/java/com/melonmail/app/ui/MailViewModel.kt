package com.melonmail.app.ui

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.melonmail.app.MelonApp
import com.melonmail.app.data.Api
import com.melonmail.app.data.AttachmentInfo
import com.melonmail.app.data.Envelope
import com.melonmail.app.data.MailCache
import com.melonmail.app.data.MsgBody
import com.melonmail.app.data.PinStore
import com.melonmail.app.data.PinnedMail
import com.melonmail.app.data.ReplyRequest
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

const val PAGE_SIZE = 50
const val INBOX = "INBOX"

/** 统一收件箱里的一项:带上它属于哪个账号(envelope id 是按账号区分的)。 */
data class AccountEnvelope(val account: String, val envelope: Envelope)

class MailViewModel(app: Application) : AndroidViewModel(app) {

    val settings = (app as MelonApp).settings
    private val cache = MailCache(app)
    private val pinStore = PinStore(app)

    // ---- 置顶(pin)----
    var pins by mutableStateOf<List<PinnedMail>>(emptyList())
        private set

    init {
        pins = pinStore.load().sortedByDescending { it.pinnedAt }
    }

    fun isPinned(account: String, id: String): Boolean =
        pins.any { it.account == account && it.envelope.id == id }

    /** 某账号某文件夹下的置顶项(账户收件箱用)。 */
    fun pinsFor(account: String, folder: String): List<PinnedMail> =
        pins.filter { it.account == account && it.folder == folder }

    /** 统一收件箱用:所有 INBOX 的置顶项。 */
    fun unifiedPins(): List<PinnedMail> = pins.filter { it.folder == INBOX }

    fun togglePin(account: String, folder: String, env: Envelope) {
        if (isPinned(account, env.id)) unpin(account, env.id) else pin(account, folder, env)
    }

    private fun persistPins() = pinStore.save(pins)

    fun pin(account: String, folder: String, env: Envelope) {
        if (isPinned(account, env.id)) return
        val pm = PinnedMail(account, folder, env, body = null, pinnedAt = System.currentTimeMillis())
        pins = listOf(pm) + pins
        persistPins()
        // 抓正文缓存进 pin(不含附件;markRead=false 避免 pin 误标已读)。离线则留空,下次有网再补。
        viewModelScope.launch {
            val body = runCatching { Api.service?.message(env.id, account, folder = folder, markRead = false) }.getOrNull()
            if (body != null) {
                pins = pins.map { if (it.account == account && it.envelope.id == env.id) it.copy(body = body) else it }
                persistPins()
            }
        }
    }

    fun unpin(account: String, id: String) {
        pins = pins.filterNot { it.account == account && it.envelope.id == id }
        persistPins()
    }

    /**
     * 服务器删除对账:某账号某文件夹刷新成功后调用。
     * 若置顶邮件落在「已加载的最新窗口」内(date >= 本页最旧)却不在结果里 → 判定已被删 → 自动 unpin。
     * 比窗口更旧(翻页之外)的置顶项无法判断,保留。
     */
    private fun reconcilePins(account: String, folder: String, fresh: List<Envelope>) {
        if (fresh.isEmpty()) return
        val ids = fresh.mapTo(HashSet()) { it.id }
        val oldest = fresh.mapNotNull { it.date }.minOrNull() ?: return
        val survivors = pins.filterNot { p ->
            p.account == account && p.folder == folder &&
                p.envelope.id !in ids &&
                (p.envelope.date?.let { it >= oldest } ?: false)
        }
        if (survivors.size != pins.size) {
            pins = survivors
            persistPins()
        }
    }

    // ---- 账户列表 ----
    var accounts by mutableStateOf<List<String>>(emptyList())
        private set
    var accountsLoading by mutableStateOf(false)
        private set
    var accountsError by mutableStateOf<String?>(null)

    // ---- 单账号收件箱 ----
    var inboxAccount by mutableStateOf("")
        private set
    var inboxFolder by mutableStateOf(INBOX)         // 当前查看的文件夹(收件箱 / 已发)
        private set
    var inbox by mutableStateOf<List<Envelope>>(emptyList())
        private set
    // 探测到的「已发」文件夹名,按账号缓存(null=未探测或该账号没有)。
    private val sentFolders = mutableStateMapOf<String, String?>()
    fun sentFolderOf(account: String): String? = sentFolders[account]
    var inboxLoading by mutableStateOf(false)        // 首次/刷新
        private set
    var inboxLoadingMore by mutableStateOf(false)    // 上拉加载
        private set
    var inboxError by mutableStateOf<String?>(null)
    var inboxHasMore by mutableStateOf(true)
        private set
    private var inboxPage = 1

    // ---- 统一收件箱(跨账号) ----
    var unified by mutableStateOf<List<AccountEnvelope>>(emptyList())
        private set
    var unifiedLoading by mutableStateOf(false)
        private set
    var unifiedLoadingMore by mutableStateOf(false)
        private set
    var unifiedError by mutableStateOf<String?>(null)
    var unifiedHasMore by mutableStateOf(true)
        private set
    private var unifiedPage = 1

    // 新鲜度:同一账户/文件夹最近联网拉过就别重复拉。统一收件箱与单账户【共享】这张表,
    // 所以统一收件箱拉过的账户,点进单账户时直接用缓存、不再重复请求(force=true 下拉刷新可绕过)。
    private val freshMs = 60_000L
    private val lastFetched = mutableMapOf<String, Long>()  // "account|folder" -> 上次成功联网时刻
    private var lastUnifiedFetch = 0L
    private fun freshKey(account: String, folder: String) = "$account|$folder"
    private fun isFresh(account: String, folder: String) =
        System.currentTimeMillis() - (lastFetched[freshKey(account, folder)] ?: 0L) < freshMs

    /** 取服务端版本号(设置页显示);失败返回 null。 */
    suspend fun fetchServerVersion(): String? =
        runCatching { Api.service?.version()?.version }.getOrNull()?.takeIf { it.isNotBlank() }

    // ---- 未读数(统一收件箱总未读 + 各账户未读;服务端 SEARCH UNSEEN 全量统计)----
    var unreadCounts by mutableStateOf<Map<String, Int>>(emptyMap())
        private set
    val unreadTotal: Int get() = unreadCounts.values.sum()
    private var unreadLoading = false

    fun loadUnread() {
        if (unreadLoading) return  // 防并发
        val svc = Api.service ?: return
        viewModelScope.launch {
            unreadLoading = true
            try {
                val resp = svc.unreadAll()
                unreadCounts = resp.counts.filterValues { it != null }.mapValues { it.value!! }
            } catch (_: Exception) {
                // 取不到就保留旧值,不打扰用户
            } finally {
                unreadLoading = false
            }
        }
    }

    fun loadAccounts() {
        if (accounts.isEmpty()) cache.loadAccounts().takeIf { it.isNotEmpty() }?.let { accounts = it }
        val svc = Api.service ?: return
        viewModelScope.launch {
            accountsLoading = true; accountsError = null
            try {
                accounts = svc.accounts().accounts
                cache.saveAccounts(accounts)
            } catch (e: Exception) {
                if (accounts.isEmpty()) accounts = cache.loadAccounts()
                accountsError = e.message ?: e.toString()
            } finally {
                accountsLoading = false
            }
        }
    }

    // ---------- 单账号 ----------

    fun loadInbox(account: String, folder: String = INBOX, force: Boolean = false) {
        if (!force && account == inboxAccount && folder == inboxFolder && inbox.isNotEmpty()) return
        inboxAccount = account
        inboxFolder = folder
        inboxPage = 1
        inboxHasMore = true
        // 先用缓存填充(离线也能看;联网成功后覆盖)
        inbox = cache.loadInbox(account, folder)
        // 新鲜度:最近已联网拉过(可能是统一收件箱拉的)→ 直接用缓存,跳过重复请求
        if (!force && isFresh(account, folder) && inbox.isNotEmpty()) {
            inboxError = null
            inboxHasMore = inbox.size >= PAGE_SIZE
            return
        }
        val svc = Api.service ?: return
        viewModelScope.launch {
            inboxLoading = true; inboxError = null
            try {
                val list = svc.inbox(account, folder = folder, page = 1, pageSize = PAGE_SIZE)
                inbox = list
                inboxHasMore = list.size >= PAGE_SIZE
                cache.saveInbox(account, folder, list)
                lastFetched[freshKey(account, folder)] = System.currentTimeMillis()
                reconcilePins(account, folder, list)  // 服务器已删的置顶项自动取消
            } catch (e: Exception) {
                if (inbox.isEmpty()) inbox = cache.loadInbox(account, folder)
                inboxError = "离线或加载失败:${e.message}"
            } finally {
                inboxLoading = false
            }
        }
    }

    fun refreshInbox() {
        if (inboxAccount.isNotBlank()) loadInbox(inboxAccount, inboxFolder, force = true)
    }

    fun loadMoreInbox() {
        val svc = Api.service ?: return
        if (inboxLoading || inboxLoadingMore || !inboxHasMore || inboxAccount.isBlank()) return
        viewModelScope.launch {
            inboxLoadingMore = true
            try {
                val next = inboxPage + 1
                val list = svc.inbox(inboxAccount, folder = inboxFolder, page = next, pageSize = PAGE_SIZE)
                if (list.isEmpty()) {
                    inboxHasMore = false
                } else {
                    inbox = inbox + list
                    inboxPage = next
                    inboxHasMore = list.size >= PAGE_SIZE
                }
            } catch (e: Exception) {
                inboxError = e.message ?: e.toString()
            } finally {
                inboxLoadingMore = false
            }
        }
    }

    /** 探测账号的「已发」文件夹名(结果缓存,供 InboxScreen 决定是否显示「已发」切换)。
     *  只缓存「探到了」的结果(非 null);探到 null(失败或服务端当时没探到)则下次进收件箱重试,
     *  这样服务端后来修好/补上已发文件夹时 app 能自愈,无需重启。 */
    fun loadFolders(account: String) {
        if (sentFolders[account] != null) return
        val svc = Api.service ?: return
        viewModelScope.launch {
            runCatching { svc.folders(account) }.onSuccess { sentFolders[account] = it.sent }
        }
    }

    fun envelopeById(id: String): Envelope? =
        inbox.firstOrNull { it.id == id } ?: unified.firstOrNull { it.envelope.id == id }?.envelope

    // ---------- 统一收件箱 ----------

    /** 从所有账号各取一页,合并;返回 (列表, 是否有账号还满页). */
    private suspend fun fetchUnifiedPage(accs: List<String>, page: Int): Pair<List<AccountEnvelope>, Boolean> {
        val svc = Api.service ?: return emptyList<AccountEnvelope>() to false
        // 各账户【并发】拉(网络 IO 并行,整轮耗时 ≈ 最慢账户,而非各账户之和)。
        val results = coroutineScope {
            accs.map { acc -> async { acc to runCatching { svc.inbox(acc, page = page, pageSize = PAGE_SIZE) } } }
                .awaitAll()
        }
        // 结果回主线程后【串行】处理:cache/置顶/新鲜度都改共享状态,串行即无并发竞争。
        val all = mutableListOf<AccountEnvelope>()
        var anyFull = false
        for ((acc, result) in results) {
            val list = result.getOrElse { emptyList() }
            if (page == 1 && result.isSuccess) {
                // 登记新鲜度:点进该单账户时即可复用、不再重复拉
                lastFetched[freshKey(acc, INBOX)] = System.currentTimeMillis()
                if (list.isNotEmpty()) {
                    cache.saveInbox(acc, INBOX, list)   // 顺手缓存,供离线
                    reconcilePins(acc, INBOX, list)     // 统一收件箱刷新也对账置顶
                }
            }
            all += list.map { AccountEnvelope(acc, it) }
            if (list.size >= PAGE_SIZE) anyFull = true
        }
        return all to anyFull
    }

    fun loadUnified(force: Boolean = false) {
        if (unifiedLoading) return  // 防并发:正在拉就不再启第二条
        // 新鲜度:最近拉过且有数据 → 用现有,跳过整轮全账户请求(下拉刷新 force=true 绕过)
        if (!force && unified.isNotEmpty() &&
            System.currentTimeMillis() - lastUnifiedFetch < freshMs) return
        // 先用缓存拼一版(离线可看)
        if (unified.isEmpty()) {
            val cachedAccs = accounts.ifEmpty { cache.loadAccounts() }
            val cached = cachedAccs.flatMap { acc -> cache.loadInbox(acc, INBOX).map { AccountEnvelope(acc, it) } }
            if (cached.isNotEmpty()) unified = cached.sortedByDescending { it.envelope.date ?: "" }
        }
        val svc = Api.service ?: return
        unifiedPage = 1
        unifiedHasMore = true
        viewModelScope.launch {
            unifiedLoading = true; unifiedError = null
            try {
                val accs = accounts.ifEmpty { svc.accounts().accounts.also { accounts = it; cache.saveAccounts(it) } }
                val (list, anyFull) = fetchUnifiedPage(accs, 1)
                if (list.isNotEmpty()) {
                    unified = list.sortedByDescending { it.envelope.date ?: "" }
                    unifiedHasMore = anyFull
                }
                lastUnifiedFetch = System.currentTimeMillis()
            } catch (e: Exception) {
                unifiedError = "离线或加载失败:${e.message}"
            } finally {
                unifiedLoading = false
            }
        }
    }

    fun loadMoreUnified() {
        if (unifiedLoading || unifiedLoadingMore || !unifiedHasMore || accounts.isEmpty()) return
        if (Api.service == null) return
        viewModelScope.launch {
            unifiedLoadingMore = true
            try {
                val next = unifiedPage + 1
                val (list, anyFull) = fetchUnifiedPage(accounts, next)
                if (list.isEmpty()) {
                    unifiedHasMore = false
                } else {
                    unified = (unified + list).sortedByDescending { it.envelope.date ?: "" }
                    unifiedPage = next
                    unifiedHasMore = anyFull
                }
            } catch (e: Exception) {
                unifiedError = e.message ?: e.toString()
            } finally {
                unifiedLoadingMore = false
            }
        }
    }

    // ---------- 读 / 发 / 回 ----------

    suspend fun loadMessage(account: String, id: String, folder: String = INBOX): Result<MsgBody> = runCatching {
        // 置顶项自带的正文缓存:网络失败时的最终兜底(常规缓存可能没有/被清)。
        val pinnedBody = pins.firstOrNull { it.account == account && it.envelope.id == id }?.body
        val svc = Api.service
            ?: return@runCatching (cache.loadMessage(account, id) ?: pinnedBody ?: error("未配置服务器地址"))
        try {
            val body = svc.message(id, account, folder = folder, markRead = true)  // 打开即标记已读
            markReadLocally(id)
            cache.saveMessage(account, id, body)                  // 缓存供离线
            body
        } catch (e: Exception) {
            cache.loadMessage(account, id) ?: pinnedBody ?: throw e   // 离线回退:常规缓存 → 置顶缓存
        }
    }

    /** 打开后把列表里这封标成已读(加 Seen),让未读样式同步消失。 */
    private fun markReadLocally(id: String) {
        inbox = inbox.map { if (it.id == id && it.isUnread) it.copy(flags = it.flags + "Seen") else it }
        unified = unified.map {
            if (it.envelope.id == id && it.envelope.isUnread) {
                it.copy(envelope = it.envelope.copy(flags = it.envelope.flags + "Seen"))
            } else {
                it
            }
        }
        // 置顶快照也同步标记已读
        if (pins.any { it.envelope.id == id && it.envelope.isUnread }) {
            pins = pins.map {
                if (it.envelope.id == id && it.envelope.isUnread) {
                    it.copy(envelope = it.envelope.copy(flags = it.envelope.flags + "Seen"))
                } else {
                    it
                }
            }
            persistPins()
        }
    }

    private fun text(s: String) = s.toRequestBody("text/plain; charset=utf-8".toMediaType())

    private fun fileParts(attachments: List<Uri>): List<MultipartBody.Part> {
        val cr = getApplication<Application>().contentResolver
        return attachments.map { uri ->
            val name = displayName(uri)
            val type = (cr.getType(uri) ?: "application/octet-stream").toMediaType()
            val bytes = cr.openInputStream(uri)?.use { it.readBytes() } ?: ByteArray(0)
            MultipartBody.Part.createFormData("files", name, bytes.toRequestBody(type))
        }
    }

    suspend fun send(
        account: String,
        to: String,
        subject: String,
        body: String,
        attachments: List<Uri>,
    ): Result<String> = runCatching {
        val svc = Api.service ?: error("未配置服务器地址")
        require(to.split(",", ";").any { it.isNotBlank() }) { "收件人不能为空" }
        svc.send(text(account), text(to), text(subject), text(body), fileParts(attachments)).detail
    }

    suspend fun reply(
        account: String,
        id: String,
        body: String,
        replyAll: Boolean,
        attachments: List<Uri>,
        folder: String = INBOX,
    ): Result<String> = runCatching {
        val svc = Api.service ?: error("未配置服务器地址")
        svc.reply(id, text(account), text(body), text(replyAll.toString()), text(folder), fileParts(attachments)).detail
    }

    suspend fun forward(
        account: String,
        id: String,
        to: String,
        body: String,
        attachments: List<Uri>,
        folder: String = INBOX,
    ): Result<String> = runCatching {
        val svc = Api.service ?: error("未配置服务器地址")
        require(to.split(",", ";").any { it.isNotBlank() }) { "收件人不能为空" }
        svc.forward(id, text(account), text(to), text(body), text(folder), fileParts(attachments)).detail
    }

    /** 删除:乐观地先从列表移除,服务器失败再恢复。删成功则同时取消置顶。 */
    fun deleteMessage(account: String, id: String, folder: String = INBOX) {
        val prevInbox = inbox
        val prevUnified = unified
        inbox = inbox.filterNot { it.id == id }
        unified = unified.filterNot { it.envelope.id == id }
        viewModelScope.launch {
            val ok = runCatching { Api.service?.deleteMessage(id, account, folder) }.getOrNull() != null
            if (ok) {
                unpin(account, id)  // 删了就不再置顶
            } else {
                inbox = prevInbox
                unified = prevUnified
                inboxError = "删除失败,已恢复"
            }
        }
    }

    fun displayName(uri: Uri): String {
        val cr = getApplication<Application>().contentResolver
        var name = "attachment"
        cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (i >= 0 && c.moveToFirst()) c.getString(i)?.let { name = it }
        }
        return name
    }

    suspend fun listAttachments(account: String, id: String, folder: String = INBOX): Result<List<AttachmentInfo>> =
        runCatching {
            val svc = Api.service ?: error("未配置服务器地址")
            svc.attachments(id, account, folder).attachments
        }

    /** 下载附件到 app 缓存目录,返回文件供打开。 */
    suspend fun downloadAttachment(account: String, id: String, name: String, folder: String = INBOX): Result<File> =
        runCatching {
            val svc = Api.service ?: error("未配置服务器地址")
            val body = svc.downloadAttachment(id, account, name, folder)
            val dir = File(getApplication<Application>().cacheDir, "attachments").apply { mkdirs() }
            val file = File(dir, name)
            body.byteStream().use { input -> file.outputStream().use { input.copyTo(it) } }
            file
        }
}
