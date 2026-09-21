package com.example.avatar

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

class AvatarApiClient {

    private val client: OkHttpClient = getUnsafeOkHttpClient()

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    companion object {
        /**
         * Crea un OkHttpClient que acepta certificados autofirmados / locales en desarrollo.
         */
        private fun getUnsafeOkHttpClient(): OkHttpClient {
            return try {
                val trustAllCerts = arrayOf<TrustManager>(
                    object : X509TrustManager {
                        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
                    }
                )

                val sslContext = SSLContext.getInstance("SSL")
                sslContext.init(null, trustAllCerts, SecureRandom())
                val sslSocketFactory = sslContext.socketFactory

                OkHttpClient.Builder()
                    .sslSocketFactory(sslSocketFactory, trustAllCerts[0] as X509TrustManager)
                    .hostnameVerifier { _, _ -> true }
                    .connectTimeout(6, TimeUnit.SECONDS)
                    .readTimeout(12, TimeUnit.SECONDS)
                    .writeTimeout(12, TimeUnit.SECONDS)
                    .build()
            } catch (e: Exception) {
                OkHttpClient.Builder()
                    .connectTimeout(6, TimeUnit.SECONDS)
                    .readTimeout(12, TimeUnit.SECONDS)
                    .writeTimeout(12, TimeUnit.SECONDS)
                    .build()
            }
        }
    }

    /**
     * Envía texto en modo "echo" para que el avatar lo reproduzca con TTS y sincronización de video.
     */
    suspend fun speak(
        serverUrl: String,
        sessionId: String,
        text: String,
        interrupt: Boolean = true
    ): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val cleanUrl = serverUrl.trimEnd('/')
            val payload = JSONObject().apply {
                put("text", text)
                put("type", "echo")
                put("interrupt", interrupt)
                put("sessionid", sessionId)
            }

            val request = Request.Builder()
                .url("$cleanUrl/human")
                .post(payload.toString().toRequestBody(jsonMediaType))
                .build()

            client.newCall(request).execute().use { response ->
                val bodyString = response.body?.string().orEmpty()

                if (response.isSuccessful) {
                    if (bodyString.isNotEmpty()) {
                        val json = JSONObject(bodyString)
                        val code = json.optInt("code", 0)
                        if (code != 0) {
                            val msg = json.optString("msg", "Error en servidor")
                            return@withContext Result.failure(Exception(msg))
                        }
                    }
                    Result.success(Unit)
                } else {
                    Result.failure(Exception("Error HTTP ${response.code}: $bodyString"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Interrumpe cualquier locución en curso del avatar.
     */
    suspend fun interrupt(
        serverUrl: String,
        sessionId: String
    ): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            val cleanUrl = serverUrl.trimEnd('/')
            val payload = JSONObject().apply {
                put("sessionid", sessionId)
            }

            val request = Request.Builder()
                .url("$cleanUrl/interrupt_talk")
                .post(payload.toString().toRequestBody(jsonMediaType))
                .build()

            client.newCall(request).execute().use { response ->
                val bodyString = response.body?.string().orEmpty()

                if (response.isSuccessful) {
                    if (bodyString.isNotEmpty()) {
                        val json = JSONObject(bodyString)
                        val code = json.optInt("code", 0)
                        if (code != 0) {
                            val msg = json.optString("msg", "Error al interrumpir")
                            return@withContext Result.failure(Exception(msg))
                        }
                    }
                    Result.success(Unit)
                } else {
                    Result.failure(Exception("Error HTTP ${response.code}: $bodyString"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Consulta si el avatar está actualmente hablando.
     */
    suspend fun isSpeaking(
        serverUrl: String,
        sessionId: String
    ): Result<Boolean> = withContext(Dispatchers.IO) {
        try {
            val cleanUrl = serverUrl.trimEnd('/')
            val payload = JSONObject().apply {
                put("sessionid", sessionId)
            }

            val request = Request.Builder()
                .url("$cleanUrl/is_speaking")
                .post(payload.toString().toRequestBody(jsonMediaType))
                .build()

            client.newCall(request).execute().use { response ->
                val bodyString = response.body?.string()
                if (response.isSuccessful && bodyString != null) {
                    val json = JSONObject(bodyString)
                    val speaking = json.optBoolean("data", false)
                    Result.success(speaking)
                } else {
                    Result.failure(Exception("HTTP ${response.code}"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Prueba rápida de conectividad con el servidor.
     */
    suspend fun ping(serverUrl: String): Result<Boolean> = withContext(Dispatchers.IO) {
        try {
            val cleanUrl = serverUrl.trimEnd('/')
            val request = Request.Builder()
                .url(cleanUrl)
                .head()
                .build()

            client.newCall(request).execute().use { response ->
                Result.success(response.isSuccessful || response.code < 500)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
