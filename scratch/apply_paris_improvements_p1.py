import re

html_path = 'web/avatar-experimental.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update checkout header HTML
old_header = re.search(r'<header class="checkout-header">.*?</header>', content, re.DOTALL)
if old_header:
    new_header = """<header class="checkout-header">
                    <div class="checkout-brand">
                        <span class="brand-logo-img">paris</span>
                        <span class="brand-divider">|</span>
                        <span class="brand-store">Bolsa de Compras · Costanera Center</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:12px;">
                        <span id="pos-header-status-pill" class="header-pos-pill" onclick="connectGetnetSerial()" title="Estado de conexión con terminal Getnet (haz clic para conectar)">
                            <span id="pos-status-bullet">●</span> <span id="pos-header-status-text">POS Getnet (Desconectado)</span>
                        </span>
                        <button class="checkout-close-btn" onclick="closeParisCheckout()" title="Volver al Asesor">
                            ← Volver a la Tienda
                        </button>
                    </div>
                </header>"""
    content = content.replace(old_header.group(0), new_header, 1)

# 2. Add Cencosud points badge in summary card if not present
if 'cenco-points-badge' not in content:
    content = content.replace(
        '<div class="summary-total-row">',
        """<div class="cenco-points-badge">
                                <span class="cenco-points-icon">⭐</span>
                                <span>Acumulas <strong id="chk-cenco-points">0</strong> Puntos Cencosud con esta compra</span>
                            </div>
                            <div class="summary-total-row">"""
    )

# 3. Fix scheduleFollowUp to auto-close map
content = content.replace(
    'function scheduleFollowUp() {\n            clearTimeout(_followUpTimeoutId);\n            clearTimeout(_followUpAckTimeoutId);\n            _waitingFollowUpAck = false;\n            if (!_conversationAwake) return;\n            _followUpTimeoutId = setTimeout(() => {\n                LOG("30 segundos de silencio → Preguntando si necesita algo más.");\n                const followUpText = "¿Necesitas algo más?";',
    'function scheduleFollowUp() {\n            clearTimeout(_followUpTimeoutId);\n            clearTimeout(_followUpAckTimeoutId);\n            _waitingFollowUpAck = false;\n            if (!_conversationAwake) return;\n            _followUpTimeoutId = setTimeout(() => {\n                LOG("30 segundos de silencio → Cerrando mapa interactivo y preguntando si necesita algo más.");\n                closeStoreMap();\n                const followUpText = "¿Necesitas algo más?";'
)

# 4. Fix speaking monitor acoustic margin (increase from 200ms to 450ms)
content = content.replace(
    '// Margen acústico optimizado (200ms) para respuesta inmediata a preguntas del avatar\n                            setTimeout(() => {\n                                if (!isListening && isConnected && !isSpeaking) {\n                                    _alwaysOnActive = false;\n                                    startAlwaysOnListening();\n                                }\n                            }, 200);',
    '// Margen acústico optimizado (450ms) para asegurar que el parlante termine de reproducir la última palabra y evitar eco/corte\n                            setTimeout(() => {\n                                if (!isListening && isConnected && !isSpeaking) {\n                                    _alwaysOnActive = false;\n                                    startAlwaysOnListening();\n                                }\n                            }, 450);'
)

# 5. Fix handleBarcodeScan to announce name first and ask: "¿Deseas agregarlo al carrito o saber información adicional del producto?"
barcode_scan_func_match = re.search(r'async function handleBarcodeScan\(code\)\s*\{.*?catch \(err\)\s*\{\s*ERR\(\'Error al buscar producto por código de barra:\', err\);\s*\}\s*\}', content, re.DOTALL)
if barcode_scan_func_match:
    new_barcode_scan_func = """async function handleBarcodeScan(code) {
            LOG(`Escáner de código de barras detectado: "${code}"`);
            try {
                // Cerrar mapa si estaba abierto para dar foco a la tarjeta del producto escaneado
                closeStoreMap();

                const res = await fetch(`/api/producto/barcode/${encodeURIComponent(code)}`);
                const result = await res.json();

                if (result.code === 0 && result.data) {
                    const prod = result.data;
                    LOG('Producto encontrado:', prod.nombre);
                    showProductCard(prod);
                    _pendingCartProduct = prod;
                    _pendingAction = 'CONFIRM_ADD_CART';
                    LOG('[Cart] Producto registrado para decisión del cliente:', prod.nombre);

                    // Desbloquear audio del video explícitamente ante el escaneo
                    const videoEl = document.getElementById('video');
                    if (videoEl && videoEl.muted) {
                        videoEl.muted = false;
                        _audioUnlocked = true;
                        if (videoEl.paused && videoEl.srcObject) {
                            videoEl.play().catch(e => WARN('play() barcode unlock:', e.name));
                        }
                    }

                    // Locución exacta y determinista requerida:
                    // 1° Nombre del producto, 2° ¿Desea agregarlo al carrito o saber información adicional del producto?
                    const scanPrompt = `Has escaneado ${prod.nombre}. ¿Deseas agregarlo al carrito o saber información adicional del producto?`;

                    const sessionid = document.getElementById('sessionid').value;
                    clearTimeout(_followUpTimeoutId);
                    clearTimeout(_followUpAckTimeoutId);
                    _waitingFollowUpAck = false;

                    clearServerHistory();
                    wakeUpModel();
                    stopAlwaysOnListening();

                    queueAvatarBubble(scanPrompt);
                    try {
                        if (_activeLLMAbortController) {
                            try { _activeLLMAbortController.abort(); } catch (e) {}
                        }
                        _activeLLMAbortController = new AbortController();

                        await fetch('/human', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                text: scanPrompt,
                                type: 'echo',
                                interrupt: true,
                                sessionid: String(sessionid)
                            }),
                            signal: _activeLLMAbortController.signal
                        });
                    } catch (e) {
                        WARN('Error al emitir locución de escaneo:', e);
                    }
                } else {
                    LOG('Producto no encontrado para código:', code);
                    const notFoundMsg = `Lo siento, el código escaneado no fue encontrado en nuestro catálogo. ¿Puedo ayudarte a buscar otro producto?`;
                    queueAvatarBubble(notFoundMsg);
                    const sessionid = document.getElementById('sessionid').value;
                    fetch('/human', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: notFoundMsg,
                            type: 'echo',
                            sessionid: String(sessionid)
                        })
                    }).catch(e => WARN('echo error:', e));
                }
            } catch (err) {
                ERR('Error al buscar producto por código de barra:', err);
            }
        }"""
    content = content.replace(barcode_scan_func_match.group(0), new_barcode_scan_func, 1)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Part 1: Header, follow-up map close, audio margin and barcode scan function updated.")
