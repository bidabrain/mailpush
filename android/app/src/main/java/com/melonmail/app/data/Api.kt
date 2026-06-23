package com.melonmail.app.data

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

/**
 * Retrofit 提供方(单例)。baseUrl / token 来自 Settings,运行时可变:
 *   - token 由拦截器每次请求动态读取(@Volatile);
 *   - baseUrl 变化时重建 Retrofit。
 * MelonApp 在启动时收集 Settings 流并调用 update()。
 */
object Api {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
    }

    @Volatile private var token: String = ""
    @Volatile private var baseUrl: String = ""
    @Volatile private var retrofit: Retrofit? = null

    private val client: OkHttpClient by lazy {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        OkHttpClient.Builder()
            .addInterceptor { chain ->
                val req = chain.request().newBuilder().apply {
                    val t = token
                    if (t.isNotBlank()) header("Authorization", "Bearer $t")
                }.build()
                chain.proceed(req)
            }
            .addInterceptor(logging)
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    /** 设置变化时调用。baseUrl 需以 / 结尾(Retrofit 要求)。 */
    @Synchronized
    fun update(baseUrl: String, token: String) {
        this.token = token
        val normalized = baseUrl.trim().let { if (it.isBlank() || it.endsWith("/")) it else "$it/" }
        if (normalized != this.baseUrl || (retrofit == null && normalized.isNotBlank())) {
            this.baseUrl = normalized
            retrofit = if (normalized.isBlank()) {
                null
            } else {
                Retrofit.Builder()
                    .baseUrl(normalized)
                    .client(client)
                    .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                    .build()
            }
        }
    }

    /** 未配置 baseUrl 时为 null;UI 据此提示去设置页。 */
    val service: MailApi?
        get() = retrofit?.create(MailApi::class.java)
}
