import re

html_path = 'web/avatar-experimental.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Replace the entire payment & pos handling section
old_payment_section = re.search(r'function openParisCheckout\(\)\s*\{.*?function handleFinishSuccessfulCheckout\(\)\s*\{.*?\}\s*\}', content, re.DOTALL)
if not old_payment_section:
    print("Could not find old payment section, trying broader match...")
    old_payment_section = re.search(r'function openParisCheckout\(\)\s*\{.*?(?=</script>\s*</body>)', content, re.DOTALL)

new_payment_section = """
        // ══════════════════════════════════════════════════════════════════════
        // GESTOR POS GETNET (INTEGRACIÓN JAVASCRIPT REAL - WEB SERIAL API)
        // ══════════════════════════════════════════════════════════════════════
        const posState = {
            connected: false,
            port: null,
            baudRate: 115200,
            isCharging: false,
            isCancelling: false,
            activeTransaction: null,
            lastPaidTime: 0,
            lastCancelTime: 0
        };

        let _isAutoConnectingPos = false;

        function initGetnetSDK() {
            if (typeof Getnet === 'undefined') {
                console.warn("[Getnet POS] SDK JS getnet.js no cargado.");
                return;
            }

            Getnet.SetCallback((msg) => {
                handleGetnetCallback(msg);
            });

            Getnet.SetLogCallback((log) => {
                LOG('[Getnet Log] ' + (typeof log === 'object' ? JSON.stringify(log) : log));
            });

            Getnet.SetTimeErrorCallback((err) => {
                handleGetnetTimeout(err);
            });

            // Autoconectar silenciosamente si el puerto ya fue previamente autorizado en este navegador
            checkAutoConnectPos();

            // Detectar conexión / desconexión física de hardware USB POS
            if (typeof navigator !== 'undefined' && navigator.serial) {
                navigator.serial.addEventListener('connect', async (e) => {
                    LOG('[Getnet POS] Conexión física USB detectada:', e.target);
                    await checkAutoConnectPos();
                });
                navigator.serial.addEventListener('disconnect', (e) => {
                    LOG('[Getnet POS] Desconexión física USB detectada:', e.target);
                    setPosConnected(false);
                });
            }
        }

        async function checkAutoConnectPos() {
            if (_isAutoConnectingPos) return;
            if (typeof navigator === 'undefined' || !navigator.serial || typeof Getnet === 'undefined') return;
            _isAutoConnectingPos = true;
            try {
                const port = await Getnet.autoConnect(posState.baudRate);
                if (port && Getnet.isConnected()) {
                    posState.port = port;
                    setPosConnected(true, "COM USB");
                    LOG('[Getnet POS] Auto-conectado exitosamente al POS Getnet.');
                    setTimeout(() => {
                        try { Getnet.Poll(); } catch (_) {}
                    }, 350);
                } else {
                    setPosConnected(false);
                }
            } catch (e) {
                console.warn("[Getnet POS] autoConnect error:", e);
                setPosConnected(false);
            } finally {
                _isAutoConnectingPos = false;
            }
        }

        function setPosConnected(connected, portDesc = "COM USB") {
            posState.connected = connected;
            const pill = document.getElementById('pos-header-status-pill');
            const pillText = document.getElementById('pos-header-status-text');
            const bullet = document.getElementById('pos-status-bullet');

            if (connected) {
                if (pill) pill.className = 'header-pos-pill online';
                if (pillText) pillText.textContent = `POS Getnet: En Línea (${portDesc})`;
                if (bullet) bullet.textContent = '●';
            } else {
                if (pill) pill.className = 'header-pos-pill';
                if (pillText) pillText.textContent = 'POS Getnet: Desconectado (Clic)';
                if (bullet) bullet.textContent = '○';
            }
        }

        async function connectGetnetSerial() {
            if (typeof Getnet === 'undefined') {
                alert("Librería de Getnet no disponible en este momento.");
                return false;
            }
            try {
                LOG('[Getnet POS] Abriendo selector de puerto COM nativo...');
                const port = await Getnet.connect(null, posState.baudRate);
                if (port) {
                    posState.port = port;
                    setPosConnected(true, "COM Directo");
                    LOG('[Getnet POS] ¡Puerto COM conectado exitosamente!');
                    setTimeout(() => {
                        try { Getnet.Poll(); } catch (_) {}
                    }, 300);
                    return true;
                }
            } catch (err) {
                ERR('Error al conectar puerto COM:', err);
                alert(`Error al conectar con el terminal POS: ${err.message || err}. Asegúrate de seleccionar el puerto donde está conectado el POS Getnet.`);
                return false;
            }
            return false;
        }

        // ─── Callback del Hardware POS Getnet ─────────────────────────────────────
        async function handleGetnetCallback(msg) {
            if (!msg) return;
            let data = msg;
            if (msg.JsonSerialized && typeof msg.JsonSerialized === 'string') {
                try { const inner = JSON.parse(msg.JsonSerialized); data = { ...msg, ...inner }; } catch (e) {}
            }
            const cmd = data.Command ?? data.FunctionCode ?? '-';
            const rc = data.ResponseCode ?? '-';
            LOG(`[Getnet CB] Cmd:${cmd} RC:${rc}`, data);

            const posTitleEl = document.getElementById('pos-interactive-title');
            const posDescEl = document.getElementById('pos-interactive-desc');

            // 1. ACK de transporte del POS (Received: true)
            if (data.Received === true) {
                if (posTitleEl) posTitleEl.textContent = "Procesando en el terminal POS...";
                if (posDescEl) posDescEl.textContent = "Acerque tarjeta, inserte chip o digite su PIN en el teclado del POS...";
                return;
            }

            // 2. Respuesta a Poll (Cmd 106)
            if (data.Command === 106 || data.FunctionCode === 106) {
                setPosConnected(true);
                return;
            }

            // 3. Respuesta explícita a CancelSale (Cmd 116)
            if (data.Command === 116 || data.FunctionCode === 116) {
                LOG('[Getnet POS] Venta cancelada confirmada por el terminal.');
                posState.isCancelling = false;
                posState.isCharging = false;
                resetPaymentUI();
                return;
            }

            // 4. Mensajes intermedios del POS (sin código definitivo aún)
            if (data.ResponseCode === undefined || data.ResponseCode === null || data.ResponseCode === '') {
                const statusMsg = data.ResponseMessage || data.Message || data.ResponseDescription;
                if (statusMsg) {
                    if (posTitleEl) posTitleEl.textContent = statusMsg;
                    if (posDescEl) posDescEl.textContent = "Siga las instrucciones en la pantalla del terminal Getnet...";
                }
                return;
            }

            // 5. Validación con ResponseCode numérico
            const respCode = Number(data.ResponseCode);

            if (posState.isCancelling) {
                posState.isCancelling = false;
                posState.isCharging = false;
                resetPaymentUI();
                return;
            }

            // Distinguir ACK inicial del comando vs Aprobación Bancaria Final
            const hasCardOrAuth = !!(data.AuthorizationCode || data.Last4Digits || data.CardBrand || data.CardType || data.SharesNumber !== undefined || data.AccountingDate || data.Pan || data.CardNumber);
            if (respCode === 0 && !hasCardOrAuth) {
                // Es solo el ACK de inicio de cobro: el POS está listo esperando tarjeta
                if (posTitleEl) posTitleEl.textContent = "Acerque o inserte tarjeta";
                if (posDescEl) posDescEl.textContent = data.ResponseMessage || "Por favor acerque tarjeta contactless o inserte chip en el POS Getnet.";
                return;
            }

            const isApproved = (respCode === 0 && hasCardOrAuth);

            if (isApproved) {
                // ¡PAGO REAL APROBADO POR EL BANCO EN EL TERMINAL FÍSICO!
                LOG('[Getnet POS] ¡VENTA APROBADA EXITOSAMENTE!', data);
                posState.isCharging = false;
                handlePaymentApproved(data);
            } else {
                // Transacción rechazada o cancelada por el cliente en el POS
                LOG('[Getnet POS] Transacción rechazada o cancelada en el POS:', data);
                posState.isCharging = false;
                const errDetail = data.ResponseMessage || data.Message || `Código de rechazo: ${respCode}`;
                alert(`Pago no completado en el terminal: ${errDetail}`);
                resetPaymentUI();
            }
        }

        function handleGetnetTimeout(err) {
            WARN('[Getnet POS] Timeout o error de tiempo:', err);
            if (posState.isCharging) {
                alert("Tiempo de espera agotado en el terminal POS. Por favor intente nuevamente.");
                resetPaymentUI();
            }
        }

        // ─── Funciones de la UI del Checkout ──────────────────────────────────────
        function openParisCheckout() {
            const overlay = document.getElementById('paris-checkout-overlay');
            if (!overlay) return;

            // Si no estamos en medio de un cobro activo, aseguramos estado limpio sin vouchers viejos
            if (!posState.isCharging) {
                const voucherView = document.getElementById('checkout-voucher-view');
                if (voucherView) voucherView.style.display = 'none';
                const posBox = document.getElementById('pos-interactive-box');
                if (posBox) posBox.style.display = 'none';
                const actionContainer = document.getElementById('checkout-action-container');
                if (actionContainer) actionContainer.style.display = 'block';
            }

            renderCheckoutCart();
            overlay.classList.add('open');
            LOG('[Checkout] Bolsa de compras abierta.');

            // Intentar auto-conexión del POS si no estuviese conectado
            if (!Getnet.isConnected()) {
                checkAutoConnectPos();
            }
        }

        function closeParisCheckout() {
            const overlay = document.getElementById('paris-checkout-overlay');
            if (overlay) overlay.classList.remove('open');
            LOG('[Checkout] Bolsa de compras cerrada.');
        }

        function clearCartInteractive() {
            _parisCart = [];
            saveCart();
            resetPaymentUI();
        }

        function renderCheckoutCart() {
            const listEl = document.getElementById('checkout-cart-list');
            const countEl = document.getElementById('chk-item-count');
            const subtotalEl = document.getElementById('chk-subtotal');
            const rowDiscountEl = document.getElementById('chk-row-discount');
            const discountEl = document.getElementById('chk-discount');
            const ivaEl = document.getElementById('chk-iva');
            const totalEl = document.getElementById('chk-total');
            const pointsEl = document.getElementById('chk-cenco-points');
            const submitBtn = document.getElementById('btn-submit-payment');

            const count = getCartItemsCount();
            const total = getCartTotal();
            const originalTotal = getCartOriginalTotal();
            const discount = Math.max(0, originalTotal - total);
            const iva = Math.round(total * 0.19);
            const cencoPoints = Math.floor(total / 100);

            if (countEl) countEl.textContent = String(count);
            if (subtotalEl) subtotalEl.textContent = `$${originalTotal.toLocaleString('es-CL')}`;
            if (totalEl) totalEl.textContent = `$${total.toLocaleString('es-CL')}`;
            if (ivaEl) ivaEl.textContent = `$${iva.toLocaleString('es-CL')}`;
            if (pointsEl) pointsEl.textContent = cencoPoints.toLocaleString('es-CL');

            if (rowDiscountEl && discountEl) {
                if (discount > 0) {
                    rowDiscountEl.style.display = 'flex';
                    discountEl.textContent = `-$${discount.toLocaleString('es-CL')}`;
                } else {
                    rowDiscountEl.style.display = 'none';
                }
            }

            if (submitBtn) {
                submitBtn.disabled = (_parisCart.length === 0 || _isPaymentProcessing || posState.isCharging);
                submitBtn.textContent = `Pagar $${total.toLocaleString('es-CL')} con POS Getnet`;
            }

            if (!listEl) return;
            if (_parisCart.length === 0) {
                listEl.innerHTML = '<div class="chk-empty-cart">🛍️ Tu bolsa está vacía.<br>Escanea un producto con el lector de barra para agregar.</div>';
                return;
            }

            listEl.innerHTML = _parisCart.map(item => `
                <div class="checkout-item-row">
                    <div class="chk-item-info">
                        <div class="chk-item-title">${item.nombre}</div>
                        <div class="chk-item-sub">${item.marca ? item.marca + ' · ' : ''}SKU: ${item.sku}</div>
                    </div>
                    <div class="chk-item-controls">
                        <button class="chk-qty-btn" onclick="updateCartItemQuantity('${item.sku}', -1)">-</button>
                        <span class="chk-item-qty">${item.cantidad}</span>
                        <button class="chk-qty-btn" onclick="updateCartItemQuantity('${item.sku}', 1)">+</button>
                    </div>
                    <div class="chk-item-price">$${(item.precio * item.cantidad).toLocaleString('es-CL')}</div>
                    <button class="chk-item-remove" onclick="removeFromCart('${item.sku}')" title="Eliminar">✕</button>
                </div>
            `).join('');
        }

        function selectCheckoutPaymentMethod(method) {
            _selectedPaymentMethod = method;
            const btnGetnet = document.getElementById('btn-pay-getnet');
            const btnCenco = document.getElementById('btn-pay-cencosud');
            const submitBtn = document.getElementById('btn-submit-payment');

            if (btnGetnet) btnGetnet.classList.toggle('active', method === 'getnet');
            if (btnCenco) btnCenco.classList.toggle('active', method === 'cencosud');

            if (submitBtn) {
                if (method === 'getnet') {
                    submitBtn.textContent = `Pagar $${getCartTotal().toLocaleString('es-CL')} con POS Getnet`;
                } else {
                    submitBtn.textContent = `Canjear Puntos Cencosud`;
                }
            }
        }

        async function handleStartCheckoutPayment() {
            const total = getCartTotal();
            if (total <= 0 || _isPaymentProcessing || posState.isCharging) return;

            // Verificar conexión con hardware Getnet
            if (typeof Getnet === 'undefined' || !Getnet.isConnected()) {
                const didConnect = await connectGetnetSerial();
                if (!didConnect) {
                    return; // El usuario canceló la selección de puerto
                }
            }

            _isPaymentProcessing = true;
            posState.isCharging = true;

            const actionContainer = document.getElementById('checkout-action-container');
            const posBox = document.getElementById('pos-interactive-box');
            const posAmountEl = document.getElementById('pos-interactive-amount');
            const posTitleEl = document.getElementById('pos-interactive-title');
            const posDescEl = document.getElementById('pos-interactive-desc');
            const voucherView = document.getElementById('checkout-voucher-view');

            if (actionContainer) actionContainer.style.display = 'none';
            if (voucherView) voucherView.style.display = 'none';
            if (posBox) posBox.style.display = 'flex';
            if (posAmountEl) posAmountEl.textContent = `$${total.toLocaleString('es-CL')}`;
            if (posTitleEl) posTitleEl.textContent = 'Iniciando terminal POS...';
            if (posDescEl) posDescEl.textContent = 'Enviando orden de cobro al terminal físico Getnet...';

            try {
                const ticketNumber = String(Math.floor(Math.random() * 899999 + 100000));
                LOG(`[Checkout] Enviando orden Getnet.Sale(${total}, ${ticketNumber}) al terminal...`);
                // Getnet.Sale(amount, ticketNumber, printOnPos, saleType, sendMessage, employeeId, timeout)
                Getnet.Sale(total, ticketNumber, false, 0, false, 1, 180);
            } catch (err) {
                ERR('Error enviando cobro a Getnet.Sale:', err);
                alert(`Error al comunicarse con el terminal POS: ${err.message || err}`);
                resetPaymentUI();
            }
        }

        function handleCancelCheckoutPayment() {
            LOG('[Checkout] Cancelando cobro en el POS...');
            posState.lastCancelTime = Date.now();
            posState.isCharging = false;
            posState.isCancelling = true;

            try {
                if (typeof Getnet !== 'undefined' && Getnet.isConnected()) {
                    Getnet.CancelSale();
                }
            } catch (e) {
                WARN('Error enviando CancelSale:', e);
            }

            resetPaymentUI();
        }

        // ─── Reseteo Integral de la UI Post-Cobro (Elimina el bug de persistencia $189.000) ───
        function resetPaymentUI() {
            _isPaymentProcessing = false;
            posState.isCharging = false;
            posState.isCancelling = false;

            const actionContainer = document.getElementById('checkout-action-container');
            const posBox = document.getElementById('pos-interactive-box');
            const voucherView = document.getElementById('checkout-voucher-view');

            // 1. Ocultar cajas interactivas y voucher
            if (posBox) posBox.style.display = 'none';
            if (voucherView) voucherView.style.display = 'none';
            if (actionContainer) actionContainer.style.display = 'block';

            // 2. Limpiar datos del voucher en el DOM
            const opEl = document.getElementById('v-op-number');
            const authEl = document.getElementById('v-auth');
            const cardEl = document.getElementById('v-card');
            const itemsListEl = document.getElementById('v-items-list');
            const totalEl = document.getElementById('v-total');
            if (opEl) opEl.textContent = '';
            if (authEl) authEl.textContent = '';
            if (cardEl) cardEl.textContent = '';
            if (itemsListEl) itemsListEl.innerHTML = '';
            if (totalEl) totalEl.textContent = '$0';

            renderCheckoutCart();
        }

        function handlePaymentApproved(saleResult) {
            const posBox = document.getElementById('pos-interactive-box');
            const voucherView = document.getElementById('checkout-voucher-view');
            const actionContainer = document.getElementById('checkout-action-container');

            if (posBox) posBox.style.display = 'none';
            if (actionContainer) actionContainer.style.display = 'none';
            if (voucherView) voucherView.style.display = 'flex';

            const total = saleResult.Amount || getCartTotal();
            const now = new Date();
            const dateStr = now.toLocaleDateString('es-CL') + ' ' + now.toLocaleTimeString('es-CL');

            const opEl = document.getElementById('v-op-number');
            const dateEl = document.getElementById('v-date');
            const authEl = document.getElementById('v-auth');
            const cardEl = document.getElementById('v-card');
            const itemsListEl = document.getElementById('v-items-list');
            const totalEl = document.getElementById('v-total');

            if (opEl) opEl.textContent = saleResult.OperationNumber || ('OP-' + Math.floor(Math.random() * 89999 + 10000));
            if (dateEl) dateEl.textContent = dateStr;
            if (authEl) authEl.textContent = saleResult.AuthorizationCode || ('GET-' + Math.floor(Math.random() * 89999 + 10000));
            if (cardEl) cardEl.textContent = (saleResult.CardBrand || 'TARJETA') + ' ' + (saleResult.CardNumber || '**** **** **** 1111');
            if (totalEl) totalEl.textContent = `$${Number(total).toLocaleString('es-CL')}`;

            if (itemsListEl && _parisCart.length > 0) {
                itemsListEl.innerHTML = _parisCart.map(i => `
                    <div class="v-row">
                        <span>${i.cantidad}x ${i.nombre.slice(0, 22)}</span>
                        <span>$${(i.precio * i.cantidad).toLocaleString('es-CL')}</span>
                    </div>
                `).join('');
            }

            // VACIAR COMPLETAMENTE EL CARRITO TRAS PAGO EXITOSO:
            _parisCart = [];
            localStorage.removeItem('paris_cart');
            updateCartWidget();

            LOG('[Checkout] Transacción completada con éxito. Carrito reseteado a $0.');
        }

        function handleFinishSuccessfulCheckout() {
            closeParisCheckout();
            resetPaymentUI();

            const thankMsg = "¡Muchas gracias por tu compra en Paris! Tu boleta electrónica ha sido emitida con éxito. Que tengas un excelente día.";
            queueAvatarBubble(thankMsg);
            stopAlwaysOnListening();

            const sessionid = document.getElementById('sessionid').value;
            fetch('/human', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: thankMsg,
                    type: 'echo',
                    sessionid: String(sessionid)
                })
            }).catch(e => WARN('echo error:', e));

            setTimeout(() => {
                sleepModel(false);
            }, 3500);
        }
"""

content = content.replace(old_payment_section.group(0), new_payment_section, 1)

# 2. Add initGetnetSDK() call to window.addEventListener('DOMContentLoaded')
if 'initGetnetSDK();' not in content:
    content = content.replace(
        "window.addEventListener('DOMContentLoaded', () => {",
        "window.addEventListener('DOMContentLoaded', () => {\n            initGetnetSDK();"
    )

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Part 3: Getnet JS Web Serial integration and payment persistence fix applied successfully.")
