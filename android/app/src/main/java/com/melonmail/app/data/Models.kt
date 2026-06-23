package com.melonmail.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Address(
    val name: String? = null,
    val addr: String? = null,
) {
    val display: String
        get() = name?.takeIf { it.isNotBlank() } ?: addr ?: ""
}

/**
 * 收件列表项。服务端 envelope JSON 还含 flags/to/has_attachment 等字段,
 * 这里只取展示需要的;其余靠 Json { ignoreUnknownKeys = true } 忽略。
 */
@Serializable
data class Envelope(
    val id: String,
    val subject: String = "",
    val from: Address? = null,
    @SerialName("to") val recipient: Address? = null,
    val date: String? = null,
    @SerialName("has_attachment") val hasAttachment: Boolean = false,
    val flags: List<String> = emptyList(),
) {
    val sender: String get() = from?.display?.takeIf { it.isNotBlank() } ?: "(未知发件人)"
    val subjectOrNone: String get() = subject.takeIf { it.isNotBlank() } ?: "(无主题)"
    val isUnread: Boolean get() = flags.none { it.contains("seen", ignoreCase = true) }
}

@Serializable
data class AccountsResponse(
    val accounts: List<String> = emptyList(),
)

@Serializable
data class VersionResponse(
    val version: String = "",
)

@Serializable
data class FoldersResponse(
    val folders: List<String> = emptyList(),
    val sent: String? = null,   // 探测到的「已发」文件夹名(无则 null)
)

@Serializable
data class SendRequest(
    val account: String,
    val to: List<String>,
    val subject: String = "",
    val body: String = "",
    val cc: List<String> = emptyList(),
    val bcc: List<String> = emptyList(),
    val html: Boolean = false,
)

@Serializable
data class ReplyRequest(
    val account: String,
    val body: String,
    @SerialName("reply_all") val replyAll: Boolean = false,
)

@Serializable
data class OkResponse(
    val ok: Boolean = true,
    val detail: String = "",
)

@Serializable
data class TokenRegister(
    val token: String,
)

@Serializable
data class RegisterResponse(
    val ok: Boolean = true,
    val added: Boolean = false,
    val count: Int = 0,
)

@Serializable
data class MsgBody(
    val html: String = "",
    val text: String = "",
)

/**
 * 置顶(pin)的邮件快照。持久化在 filesDir/pins(不参与自动清理),
 * 自带正文缓存(body,不含附件),所以即使常规缓存被清也能读。
 */
@Serializable
data class PinnedMail(
    val account: String,
    val folder: String = "INBOX",
    val envelope: Envelope,
    val body: MsgBody? = null,   // pin 时抓的正文;离线 pin 时可能为 null,联网后补
    val pinnedAt: Long = 0,      // 置顶区内部排序(pin 时间倒序)
)

@Serializable
data class AttachmentInfo(
    val name: String,
    val size: Long = 0,
)

@Serializable
data class AttachmentsResponse(
    val attachments: List<AttachmentInfo> = emptyList(),
)
