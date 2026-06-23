package com.melonmail.app.data

import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming

/** 与 server 的 FastAPI 端点一一对应。所有请求由拦截器自动带 Bearer token。 */
interface MailApi {

    @GET("accounts")
    suspend fun accounts(): AccountsResponse

    /** 服务端版本号(无需鉴权)。 */
    @GET("version")
    suspend fun version(): VersionResponse

    /** 自动上报本机 FCM token(多设备)。 */
    @POST("register-token")
    suspend fun registerToken(@Body req: TokenRegister): RegisterResponse

    @GET("inbox")
    suspend fun inbox(
        @Query("account") account: String,
        @Query("folder") folder: String = "INBOX",
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
    ): List<Envelope>

    /** 列出账号文件夹 + 探测到的「已发」文件夹名。 */
    @GET("folders")
    suspend fun folders(@Query("account") account: String): FoldersResponse

    /** 返回 {html, text}:优先 html(WebView 渲染),无则 text。 */
    @GET("msg/{id}")
    suspend fun message(
        @Path("id") id: String,
        @Query("account") account: String,
        @Query("folder") folder: String = "INBOX",
        @Query("mark_read") markRead: Boolean = false,
    ): MsgBody

    /** 发信:multipart(文字字段 + 可选附件)。 */
    @Multipart
    @POST("send")
    suspend fun send(
        @Part("account") account: RequestBody,
        @Part("to") to: RequestBody,
        @Part("subject") subject: RequestBody,
        @Part("body") body: RequestBody,
        @Part files: List<MultipartBody.Part>,
    ): OkResponse

    /** 回复:multipart(正文 + reply_all + 可选附件)。 */
    @Multipart
    @POST("reply/{id}")
    suspend fun reply(
        @Path("id") id: String,
        @Part("account") account: RequestBody,
        @Part("body") body: RequestBody,
        @Part("reply_all") replyAll: RequestBody,
        @Part("folder") folder: RequestBody,
        @Part files: List<MultipartBody.Part>,
    ): OkResponse

    /** 转发:multipart(收件人 + 正文 + 可选附件;原附件由服务端自动带上)。 */
    @Multipart
    @POST("forward/{id}")
    suspend fun forward(
        @Path("id") id: String,
        @Part("account") account: RequestBody,
        @Part("to") to: RequestBody,
        @Part("body") body: RequestBody,
        @Part("folder") folder: RequestBody,
        @Part files: List<MultipartBody.Part>,
    ): OkResponse

    /** 删除邮件(移到回收站)。 */
    @DELETE("msg/{id}")
    suspend fun deleteMessage(
        @Path("id") id: String,
        @Query("account") account: String,
        @Query("folder") folder: String = "INBOX",
    ): OkResponse

    /** 列出某封邮件的附件(服务端会把附件下到 /data 缓存后返回文件名/大小)。 */
    @GET("attachments/{id}")
    suspend fun attachments(
        @Path("id") id: String,
        @Query("account") account: String,
        @Query("folder") folder: String = "INBOX",
    ): AttachmentsResponse

    /** 下载某个附件的二进制流。 */
    @Streaming
    @GET("attachment/{id}")
    suspend fun downloadAttachment(
        @Path("id") id: String,
        @Query("account") account: String,
        @Query("name") name: String,
        @Query("folder") folder: String = "INBOX",
    ): ResponseBody
}
