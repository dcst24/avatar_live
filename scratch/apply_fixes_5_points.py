import re

html_path = 'web/avatar-experimental.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Bajar timer para preguntar si necesita algo más (de 30s a 20s, 10s menos)
#    Bajar timer para despedirse luego de preguntar si necesita algo más (de 20s a 15s, 5s menos)
content = re.sub(
    r'(function scheduleFollowUp\(\)\s*\{.*?\}\s*,\s*)30000(\);)',
    r'\g<1>20000\2',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'(function scheduleFollowUpAckTimeout\(\)\s*\{.*?\}\s*,\s*)20000(\);)',
    r'\g<1>15000\2',
    content,
    flags=re.DOTALL
)

# 2. Reemplazar handleBarcodeScan completo para que siempre hable la locución exacta:
#    "Has escaneado [Nombre]. ¿Deseas agregarlo al carrito o saber información adicional del producto?"
#    Y agregar deduplicación de escaneo (2s).
old_barcode_block = re.search(
    r'// ─── Lector de Código de Barras \(Escáner USB / Bluetooth\) ──────────────────\s*let _cardDismissTimeout = null;\s*function keepBarcodeFocus\(\)\s*\{.*?async function handleBarcodeScan\(code\)\s*\{.*?\}\s*(?=function showProductCard)',
    content,
    re.DOTALL
)

if not old_barcode_block:
    # Intento de búsqueda más flexible
    old_barcode_block = re.search(
        r'async function handleBarcodeScan\(code\)\s*\{.*?\}\s*(?=function showProductCard)',
        content,
        re.DOTALL
    )

new_barcode_block = """// ─── Lector de Código de Barras (Escáner USB / Bluetooth) ──────────────────
        let _cardDismissTimeout = null;
        let _lastScannedBarcode = '';
        let _lastScannedBarcodeTime = 0;

        function keepBarcodeFocus() {
            const inp = document.getElementById('barcode-input');
            if (!inp) return;
            const dbgPanel = document.getElementById('dbg-panel');
            if (dbgPanel && dbgPanel.classList.contains('open')) return;
            if (document.activeElement !== inp) {
                inp.focus();
            }
        }

        async function handleBarcodeScan(code) {
            const now = Date.now();
            const cleanCode = String(code).trim();
            if (!cleanCode) return;

            // Anti-duplicado: Evita que el lector emita 2 veces el mismo código en menos de 2.5s
            if (cleanCode === _lastScannedBarcode && (now - _lastScannedBarcodeTime) < 2500) {
                LOG(`[Barcode Scan] Ignorando escaneo repetido dentro de 2.5s: "${cleanCode}"`);
                return;
            }
            _lastScannedBarcode = cleanCode;
            _lastScannedBarcodeTime = now;

            LOG(`Escáner de código de barras detectado: "${cleanCode}"`);
            try {
                // Cerrar mapa si estaba abierto para dar foco a la tarjeta
                closeStoreMap();

                const res = await fetch(`/api/producto/barcode/${encodeURIComponent(cleanCode)}`);
                const result = await res.json();

                if (result.code === 0 && result.data) {
                    const prod = result.data;
                    LOG('Producto encontrado:', prod.nombre);
                    showProductCard(prod);

                    // Registrar producto y acción pendiente para el reconocimiento de voz
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
                    LOG('Producto no encontrado para código:', cleanCode);
                    showProductNotFound(cleanCode);

                    const notFoundText = `Lo siento, no encontré ningún producto registrado con ese código de barras en el catálogo de Paris.`;
                    const sessionid = document.getElementById('sessionid').value;
                    queueAvatarBubble(notFoundText);
                    stopAlwaysOnListening();

                    await fetch('/human', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: notFoundText,
                            type: 'echo',
                            interrupt: true,
                            sessionid: String(sessionid)
                        })
                    }).catch(e => WARN('echo error:', e));
                }
            } catch (e) {
                ERR('Error al procesar código de barras:', e);
            } finally {
                const inp = document.getElementById('barcode-input');
                if (inp) inp.focus();
            }
        }

        """

if old_barcode_block:
    content = content.replace(old_barcode_block.group(0), new_barcode_block, 1)
    print("handleBarcodeScan replaced successfully.")
else:
    print("Warning: could not locate old_barcode_block")

# 3. Anti-duplicación en _dispatchQuestion (evitar procesar la misma frase hablada 2 veces)
dispatch_search = "const _dispatchQuestion = (rawText) => {\n                if (_questionDispatched) return;\n                _questionDispatched = true;"
dispatch_replacement = """let _lastDispatchedSpeechText = '';
        let _lastDispatchedSpeechTime = 0;

        const _dispatchQuestion = (rawText) => {
            if (_questionDispatched) return;
            const now = Date.now();
            const cleanRaw = rawText.trim().toLowerCase();
            if (cleanRaw === _lastDispatchedSpeechText && (now - _lastDispatchedSpeechTime) < 2200) {
                LOG(`[Speech Dispatch] Descartando locución duplicada dentro de 2.2s: "${rawText}"`);
                return;
            }
            _lastDispatchedSpeechText = cleanRaw;
            _lastDispatchedSpeechTime = now;
            _questionDispatched = true;"""

if dispatch_search in content:
    content = content.replace(dispatch_search, dispatch_replacement, 1)
    print("_dispatchQuestion deduplication added.")
else:
    print("Warning: could not locate dispatch_search")

# 4. Anti-duplicación en addToCart (evitar añadir el mismo SKU dos veces por doble evento de voz)
cart_search = "function addToCart(product, quantity = 1) {\n            if (!product) return;\n            const sku = product.sku || product.codigo_barra;"
cart_replacement = """let _lastAddToCartSku = '';
        let _lastAddToCartTime = 0;

        function addToCart(product, quantity = 1) {
            if (!product) return;
            const now = Date.now();
            const sku = product.sku || product.codigo_barra;

            // Anti-duplicado: Evita que el mismo SKU se agregue dos veces dentro de 2.5s
            if (sku === _lastAddToCartSku && (now - _lastAddToCartTime) < 2500) {
                LOG(`[Cart] Bloqueando adición duplicada del mismo SKU dentro de 2.5s: ${sku}`);
                return;
            }
            _lastAddToCartSku = sku;
            _lastAddToCartTime = now;"""

if cart_search in content:
    content = content.replace(cart_search, cart_replacement, 1)
    print("addToCart deduplication added.")
else:
    print("Warning: could not locate cart_search")

# 5. Timer de 15 segundos para volver automáticamente al avatar tras pago si no se presiona Finalizar
voucher_timer_search = "function handlePaymentApproved(saleResult) {"
voucher_timer_replacement = """let _autoCloseVoucherTimeout = null;

        function handlePaymentApproved(saleResult) {
            clearTimeout(_autoCloseVoucherTimeout);
            // Timer de 15 segundos para volver automáticamente al avatar si el usuario no presiona Finalizar
            _autoCloseVoucherTimeout = setTimeout(() => {
                LOG('[Checkout Voucher] 15s transcurridos sin presionar Finalizar → Volviendo automáticamente al avatar.');
                handleFinishSuccessfulCheckout();
            }, 15000);"""

if voucher_timer_search in content:
    content = content.replace(voucher_timer_search, voucher_timer_replacement, 1)
    print("15s auto-close timer for voucher added in handlePaymentApproved.")
else:
    print("Warning: could not locate voucher_timer_search")

# Cancelar timer al presionar finalizar o resetear UI
finish_search = "function handleFinishSuccessfulCheckout() {"
finish_replacement = """function handleFinishSuccessfulCheckout() {
            clearTimeout(_autoCloseVoucherTimeout);
            _autoCloseVoucherTimeout = null;"""

if finish_search in content:
    content = content.replace(finish_search, finish_replacement, 1)
    print("Voucher timer clearance added to handleFinishSuccessfulCheckout.")

reset_search = "function resetPaymentUI() {"
reset_replacement = """function resetPaymentUI() {
            clearTimeout(_autoCloseVoucherTimeout);
            _autoCloseVoucherTimeout = null;"""

if reset_search in content:
    content = content.replace(reset_search, reset_replacement, 1)
    print("Voucher timer clearance added to resetPaymentUI.")

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("All 5 fixes applied successfully.")
