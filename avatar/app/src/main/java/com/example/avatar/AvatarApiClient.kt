package com.example.avatar

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class AvatarApiClient {

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

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

            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Error en servidor: HTTP ${response.code}"))
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

            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Error al interrumpir: HTTP ${response.code}"))
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

            val response = client.newCall(request).execute()
            val bodyString = response.body?.string()
            if (response.isSuccessful && bodyString != null) {
                val json = JSONObject(bodyString)
                val speaking = json.optBoolean("data", false)
                Result.success(speaking)
            } else {
                Result.failure(Exception("HTTP ${response.code}"))
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

            val response = client.newCall(request).execute()
            Result.success(response.isSuccessful || response.code < 500)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
