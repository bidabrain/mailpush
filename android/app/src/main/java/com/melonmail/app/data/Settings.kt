package com.melonmail.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "settings")

/** 本地设置:server 地址、API token、当前 FCM token、默认账号。凭据只存本机。 */
class Settings(private val context: Context) {

    private object Keys {
        val BASE_URL = stringPreferencesKey("base_url")
        val API_TOKEN = stringPreferencesKey("api_token")
        val FCM_TOKEN = stringPreferencesKey("fcm_token")
        val DEFAULT_ACCOUNT = stringPreferencesKey("default_account")
    }

    val baseUrl: Flow<String> = context.dataStore.data.map { it[Keys.BASE_URL] ?: "" }
    val apiToken: Flow<String> = context.dataStore.data.map { it[Keys.API_TOKEN] ?: "" }
    val fcmToken: Flow<String> = context.dataStore.data.map { it[Keys.FCM_TOKEN] ?: "" }
    val defaultAccount: Flow<String> = context.dataStore.data.map { it[Keys.DEFAULT_ACCOUNT] ?: "" }

    suspend fun setBaseUrl(value: String) = context.dataStore.edit { it[Keys.BASE_URL] = value.trim() }
    suspend fun setApiToken(value: String) = context.dataStore.edit { it[Keys.API_TOKEN] = value.trim() }
    suspend fun setFcmToken(value: String) = context.dataStore.edit { it[Keys.FCM_TOKEN] = value }
    suspend fun setDefaultAccount(value: String) = context.dataStore.edit { it[Keys.DEFAULT_ACCOUNT] = value }
}
