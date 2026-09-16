package com.example.avatar

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.os.Bundle
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.RadioButton
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.example.avatar.databinding.ActivityMainBinding
import com.example.avatar.databinding.DialogServerConfigBinding
import com.google.android.material.chip.Chip
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val avatarClient = AvatarApiClient()
    private lateinit var prefs: SharedPreferences

    private var serverProtocol: String = "http"
    private var serverHost: String = "10.0.2.2"
    private var serverPort: Int = 8010
    private var currentSessionId: String = "0"
    private var isConnected: Boolean = false
    private var speakingMonitorJob: Job? = null

    companion object {
        private const val TAG = "AvatarMainActivity"
        private const val PREFS_NAME = "avatar_prefs"
        private const val KEY_PROTOCOL = "server_protocol"
        private const val KEY_HOST = "server_host"
        private const val KEY_PORT = "server_port"
    }

    private val fullServerUrl: String
        get() = "$serverProtocol://$serverHost:$serverPort"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        ViewCompat.setOnApplyWindowInsetsListener(binding.mainRoot) { v, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(
                systemBars.left,
                systemBars.top,
                systemBars.right,
                if (ime.bottom > 0) ime.bottom else systemBars.bottom
            )
            insets
        }

        loadPreferences()
        setupUI()
        setupWebView()
    }

    private fun loadPreferences() {
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        serverProtocol = prefs.getString(KEY_PROTOCOL, "http") ?: "http"
        serverHost = prefs.getString(KEY_HOST, "10.0.2.2") ?: "10.0.2.2"
        serverPort = prefs.getInt(KEY_PORT, 8010)
    }

    private fun savePreferences(protocol: String, host: String, port: Int) {
        serverProtocol = protocol
        serverHost = host
        serverPort = port
        prefs.edit()
            .putString(KEY_PROTOCOL, protocol)
            .putString(KEY_HOST, host)
            .putInt(KEY_PORT, port)
            .apply()
        updateServerDisplay()
    }

    private fun updateServerDisplay() {
        binding.tvServerUrl.text = fullServerUrl
    }

    private fun setupUI() {
        updateServerDisplay()

        // Botón Configuración de Servidor
        binding.btnSettings.setOnClickListener {
            showServerConfigDialog()
        }

        // Chip de Estado y Botón de Reintento
        binding.statusChip.setOnClickListener {
            if (!isConnected) {
                reconnectWebRTC()
            }
        }
        binding.btnRetryConnect.setOnClickListener {
            reconnectWebRTC()
        }

        // Botón Hablar / Enviar Texto
        binding.btnSpeak.setOnClickListener {
            val text = binding.etMessage.text?.toString()?.trim().orEmpty()
            if (text.isNotEmpty()) {
                sendTextToAvatar(text)
            } else {
                Toast.makeText(this, "Ingresa un texto para que el avatar hable", Toast.LENGTH_SHORT).show()
            }
        }

        // Botón Detener / Interrumpir
        binding.btnStop.setOnClickListener {
            interruptAvatar()
        }

        // Preset Chips
        setupPresetChips()
    }

    private fun setupPresetChips() {
        val presetListener = View.OnClickListener { v ->
            if (v is Chip) {
                val phrase = v.text.toString()
                binding.etMessage.setText(phrase)
                sendTextToAvatar(phrase)
            }
        }
        binding.chipPreset1.setOnClickListener(presetListener)
        binding.chipPreset2.setOnClickListener(presetListener)
        binding.chipPreset3.setOnClickListener(presetListener)
        binding.chipPreset4.setOnClickListener(presetListener)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val webView = binding.webviewPlayer
        val settings: WebSettings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowFileAccess = true
        settings.loadsImagesAutomatically = true

        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        webView.setBackgroundColor(0) // Transparente

        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest?) {
                // Auto-conceder permisos para audio/video WebRTC en WebView
                runOnUiThread {
                    request?.grant(request.resources)
                }
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                Log.d(TAG, "WebView page finished: $url")
            }
        }

        // Registrar puente JavaScript <-> Kotlin
        webView.addJavascriptInterface(WebAppInterface(), "AndroidBridge")

        // Cargar reproductor local
        webView.loadUrl("file:///android_asset/avatar_player.html")
    }

    private fun reconnectWebRTC() {
        updateStatusChip("connecting", "Conectando…")
        binding.layoutReconnect.visibility = View.GONE
        val jsCommand = "javascript:connect('$fullServerUrl');"
        binding.webviewPlayer.evaluateJavascript(jsCommand, null)
    }

    private fun sendTextToAvatar(text: String) {
        lifecycleScope.launch {
            binding.btnSpeak.isEnabled = false
            updateStatusChip("speaking", "Sintetizando…")

            val result = avatarClient.speak(
                serverUrl = fullServerUrl,
                sessionId = currentSessionId,
                text = text,
                interrupt = true
            )

            binding.btnSpeak.isEnabled = true
            if (result.isSuccess) {
                Log.d(TAG, "Texto enviado con éxito al avatar: $text")
            } else {
                val error = result.exceptionOrNull()?.message ?: "Error desconocido"
                Log.e(TAG, "Error al enviar texto: $error")
                Toast.makeText(this@MainActivity, "Error: $error", Toast.LENGTH_SHORT).show()
                if (isConnected) {
                    updateStatusChip("connected", "Conectado")
                }
            }
        }
    }

    private fun interruptAvatar() {
        lifecycleScope.launch {
            val result = avatarClient.interrupt(
                serverUrl = fullServerUrl,
                sessionId = currentSessionId
            )
            if (result.isSuccess) {
                Log.d(TAG, "Locución interrumpida con éxito")
                if (isConnected) {
                    updateStatusChip("connected", "Conectado")
                }
            } else {
                Log.e(TAG, "Error al interrumpir: ${result.exceptionOrNull()?.message}")
            }
        }
    }

    private fun startSpeakingMonitor() {
        speakingMonitorJob?.cancel()
        speakingMonitorJob = lifecycleScope.launch {
            while (isActive && isConnected) {
                delay(700)
                val result = avatarClient.isSpeaking(fullServerUrl, currentSessionId)
                if (result.isSuccess) {
                    val speaking = result.getOrDefault(false)
                    if (speaking) {
                        updateStatusChip("speaking", "Hablando…")
                    } else if (isConnected) {
                        updateStatusChip("connected", "Conectado")
                    }
                }
            }
        }
    }

    private fun stopSpeakingMonitor() {
        speakingMonitorJob?.cancel()
        speakingMonitorJob = null
    }

    private fun updateStatusChip(state: String, text: String) {
        runOnUiThread {
            when (state) {
                "connected" -> {
                    isConnected = true
                    binding.statusChip.text = "🟢 $text"
                    binding.statusChip.setTextColor(ContextCompat.getColor(this, R.color.status_connected))
                    binding.statusChip.setChipBackgroundColorResource(R.color.status_connected_bg)
                    binding.statusChip.setChipStrokeColorResource(R.color.status_connected)
                    binding.layoutReconnect.visibility = View.GONE
                }
                "connecting" -> {
                    binding.statusChip.text = "🟡 $text"
                    binding.statusChip.setTextColor(ContextCompat.getColor(this, R.color.status_connecting))
                    binding.statusChip.setChipBackgroundColorResource(R.color.status_connecting_bg)
                    binding.statusChip.setChipStrokeColorResource(R.color.status_connecting)
                    binding.layoutReconnect.visibility = View.GONE
                }
                "speaking" -> {
                    binding.statusChip.text = "🗣️ $text"
                    binding.statusChip.setTextColor(ContextCompat.getColor(this, R.color.status_speaking))
                    binding.statusChip.setChipBackgroundColorResource(R.color.status_speaking_bg)
                    binding.statusChip.setChipStrokeColorResource(R.color.status_speaking)
                    binding.layoutReconnect.visibility = View.GONE
                }
                else -> { // disconnected or error
                    isConnected = false
                    stopSpeakingMonitor()
                    binding.statusChip.text = "🔴 $text"
                    binding.statusChip.setTextColor(ContextCompat.getColor(this, R.color.status_disconnected))
                    binding.statusChip.setChipBackgroundColorResource(R.color.status_disconnected_bg)
                    binding.statusChip.setChipStrokeColorResource(R.color.status_disconnected)
                    binding.layoutReconnect.visibility = View.VISIBLE
                    binding.tvErrorDetail.text = "No se pudo conectar con el Avatar en $fullServerUrl"
                }
            }
        }
    }

    private fun showServerConfigDialog() {
        val dialogBinding = DialogServerConfigBinding.inflate(LayoutInflater.from(this))

        if (serverProtocol.equals("https", ignoreCase = true)) {
            dialogBinding.rbHttps.isChecked = true
        } else {
            dialogBinding.rbHttp.isChecked = true
        }

        dialogBinding.etIp.setText(serverHost)
        dialogBinding.etPort.setText(serverPort.toString())

        AlertDialog.Builder(this)
            .setView(dialogBinding.root)
            .setPositiveButton(R.string.btn_save) { dialog, _ ->
                val protocol = if (dialogBinding.rbHttps.isChecked) "https" else "http"
                val host = dialogBinding.etIp.text?.toString()?.trim().orEmpty().ifEmpty { "10.0.2.2" }
                val port = dialogBinding.etPort.text?.toString()?.trim()?.toIntOrNull() ?: 8010

                savePreferences(protocol, host, port)
                reconnectWebRTC()
                dialog.dismiss()
            }
            .setNegativeButton(R.string.btn_cancel) { dialog, _ ->
                dialog.dismiss()
            }
            .show()
    }

    override fun onDestroy() {
        stopSpeakingMonitor()
        binding.webviewPlayer.destroy()
        super.onDestroy()
    }

    /**
     * Puente JavaScript Interface expuesto al WebView.
     */
    inner class WebAppInterface {

        @JavascriptInterface
        fun onPlayerReady() {
            Log.d(TAG, "[Bridge] onPlayerReady -> conectando a $fullServerUrl")
            runOnUiThread {
                reconnectWebRTC()
            }
        }

        @JavascriptInterface
        fun onSessionReady(sessionId: String) {
            Log.d(TAG, "[Bridge] onSessionReady: $sessionId")
            currentSessionId = sessionId
            isConnected = true
            updateStatusChip("connected", "Conectado")
            startSpeakingMonitor()
        }

        @JavascriptInterface
        fun onConnectionStateChange(state: String, message: String) {
            Log.d(TAG, "[Bridge] onConnectionStateChange: state=$state, msg=$message")
            runOnUiThread {
                when (state) {
                    "connected" -> {
                        isConnected = true
                        updateStatusChip("connected", "Conectado")
                        startSpeakingMonitor()
                    }
                    "connecting" -> {
                        updateStatusChip("connecting", message.ifEmpty { "Conectando…" })
                    }
                    "disconnected" -> {
                        isConnected = false
                        updateStatusChip("disconnected", "Desconectado")
                    }
                    "error" -> {
                        isConnected = false
                        updateStatusChip("disconnected", "Error de conexión")
                    }
                }
            }
        }

        @JavascriptInterface
        fun onError(errorMsg: String) {
            Log.e(TAG, "[Bridge] onError: $errorMsg")
            runOnUiThread {
                updateStatusChip("disconnected", "Error")
                Toast.makeText(this@MainActivity, "WebRTC: $errorMsg", Toast.LENGTH_SHORT).show()
            }
        }

        @JavascriptInterface
        fun onLog(msg: String) {
            Log.d(TAG, "[JS] $msg")
        }
    }
}