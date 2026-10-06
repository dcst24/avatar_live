import re

with open('web/avatar-experimental.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update scheduleFollowUp to not trigger if checkout is open
old_followup = """        function scheduleFollowUp() {
            clearTimeout(_followUpTimeoutId);
            clearTimeout(_followUpAckTimeoutId);
            _waitingFollowUpAck = false;
            if (!_conversationAwake) return;"""

new_followup = """        function scheduleFollowUp() {
            clearTimeout(_followUpTimeoutId);
            clearTimeout(_followUpAckTimeoutId);
            _waitingFollowUpAck = false;
            if (!_conversationAwake) return;
            const checkoutEl = document.getElementById('paris-checkout-overlay');
            if (checkoutEl && checkoutEl.classList.contains('open')) return;"""

assert old_followup in content, "old_followup not found"
content = content.replace(old_followup, new_followup, 1)

# 2. Update POS result & checkout functions (handleGetnetCallback, handleGetnetTimeout, openParisCheckout, closeParisCheckout)
old_pos_block = """            const isApproved = (respCode === 0 && hasCardOrAuth);

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
        }"""

new_pos_block = """            const isApproved = (respCode === 0 && hasCardOrAuth);

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
                
                // Locución: el avatar anuncia el rechazo mientras la web de pago sigue activa
                const rejectMsg = "Pago rechazado. Por favor intenta nuevamente o utiliza otro medio de pago.";
                queueAvatarBubble(rejectMsg);
                wakeUpModel();
                stopAlwaysOnListening();
                const sessionid = document.getElementById('sessionid').value;
                fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: rejectMsg,
                        type: 'echo',
                        interrupt: true,
                        sessionid: String(sessionid)
                    })
                }).catch(e => WARN('echo error:', e));

                resetPaymentUI();
                showCheckoutNotice(`Pago rechazado en el terminal: ${errDetail}`);
            }
        }

        function handleGetnetTimeout(err) {
            WARN('[Getnet POS] Timeout o error de tiempo:', err);
            if (posState.isCharging) {
                posState.isCharging = false;
                const timeoutMsg = "Pago rechazado por tiempo de espera agotado en el terminal. Por favor intenta nuevamente.";
                queueAvatarBubble(timeoutMsg);
                wakeUpModel();
                stopAlwaysOnListening();
                const sessionid = document.getElementById('sessionid').value;
                fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: timeoutMsg,
                        type: 'echo',
                        interrupt: true,
                        sessionid: String(sessionid)
                    })
                }).catch(e => WARN('echo error:', e));

                resetPaymentUI();
                showCheckoutNotice("Tiempo de espera agotado en el terminal POS.");
            }
        }

        function showCheckoutNotice(msg) {
            let noticeEl = document.getElementById('checkout-status-notice');
            if (!noticeEl) {
                const actionContainer = document.getElementById('checkout-action-container');
                if (actionContainer) {
                    noticeEl = document.createElement('div');
                    noticeEl.id = 'checkout-status-notice';
                    noticeEl.style.cssText = 'margin:12px 0;padding:10px 14px;border-radius:10px;background:#fef2f2;border:1px solid #f87171;color:#b91c1c;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;';
                    actionContainer.insertBefore(noticeEl, actionContainer.firstChild);
                }
            }
            if (noticeEl) {
                noticeEl.innerHTML = `<span>⚠️</span> <span>${msg}</span>`;
                noticeEl.style.display = 'flex';
                setTimeout(() => {
                    if (noticeEl) noticeEl.style.display = 'none';
                }, 6000);
            }
        }

        // ─── Funciones de la UI del Checkout ──────────────────────────────────────
        function openParisCheckout() {
            const overlay = document.getElementById('paris-checkout-overlay');
            if (!overlay) return;

            const wasOpen = overlay.classList.contains('open');

            // Pausar timers de seguimiento para no interrumpir el flujo de compra
            clearTimeout(_followUpTimeoutId);
            clearTimeout(_followUpAckTimeoutId);
            _waitingFollowUpAck = false;

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

            // Si se acaba de abrir, avisar mediante locución del avatar
            if (!wasOpen) {
                const transferMsg = _parisCart.length > 0
                    ? "Estás siendo transferido a la web de pago."
                    : "Tu bolsa de compras está vacía. Escanea un producto para comenzar.";
                queueAvatarBubble(transferMsg);
                wakeUpModel();
                stopAlwaysOnListening();
                const sessionid = document.getElementById('sessionid').value;
                fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: transferMsg,
                        type: 'echo',
                        interrupt: true,
                        sessionid: String(sessionid)
                    })
                }).catch(e => WARN('echo error:', e));
            }

            // Intentar auto-conexión del POS si no estuviese conectado
            if (!Getnet.isConnected()) {
                checkAutoConnectPos();
            }
        }

        function closeParisCheckout() {
            const overlay = document.getElementById('paris-checkout-overlay');
            if (overlay) overlay.classList.remove('open');
            LOG('[Checkout] Bolsa de compras cerrada.');
            if (_autoCloseVoucherTimeout) {
                handleFinishSuccessfulCheckout();
            }
        }"""

assert old_pos_block in content, "old_pos_block not found"
content = content.replace(old_pos_block, new_pos_block, 1)

# 3. Update handlePaymentApproved (speak "¡Pago exitoso!") and handleFinishSuccessfulCheckout (speak thank you upon closing)
old_approved_block = """        let _autoCloseVoucherTimeout = null;

        function handlePaymentApproved(saleResult) {
            clearTimeout(_autoCloseVoucherTimeout);
            // Timer de 15 segundos para volver automáticamente al avatar si el usuario no presiona Finalizar
            _autoCloseVoucherTimeout = setTimeout(() => {
                LOG('[Checkout Voucher] 15s transcurridos sin presionar Finalizar → Volviendo automáticamente al avatar.');
                handleFinishSuccessfulCheckout();
            }, 15000);
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
            clearTimeout(_autoCloseVoucherTimeout);
            _autoCloseVoucherTimeout = null;
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
        }"""

new_approved_block = """        let _autoCloseVoucherTimeout = null;

        function handlePaymentApproved(saleResult) {
            clearTimeout(_autoCloseVoucherTimeout);
            // Timer de 15 segundos para volver automáticamente al avatar si el usuario no presiona Finalizar
            _autoCloseVoucherTimeout = setTimeout(() => {
                LOG('[Checkout Voucher] 15s transcurridos sin presionar Finalizar → Volviendo automáticamente al avatar.');
                handleFinishSuccessfulCheckout();
            }, 15000);
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

            // Locución con la página de comprobante aún activa en pantalla:
            const successMsg = "¡Pago exitoso! Tu comprobante ha sido emitido.";
            queueAvatarBubble(successMsg);
            wakeUpModel();
            stopAlwaysOnListening();
            const sessionid = document.getElementById('sessionid').value;
            fetch('/human', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: successMsg,
                    type: 'echo',
                    interrupt: true,
                    sessionid: String(sessionid)
                })
            }).catch(e => WARN('echo error:', e));
        }

        function handleFinishSuccessfulCheckout() {
            if (_autoCloseVoucherTimeout) {
                clearTimeout(_autoCloseVoucherTimeout);
                _autoCloseVoucherTimeout = null;
            }
            closeParisCheckout();
            resetPaymentUI();

            // Agradecimiento por comprar tras cerrarse la ventana de pago:
            const thankMsg = "¡Muchas gracias por tu compra en Paris! Que tengas un excelente día.";
            queueAvatarBubble(thankMsg);
            wakeUpModel();
            stopAlwaysOnListening();

            const sessionid = document.getElementById('sessionid').value;
            fetch('/human', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: thankMsg,
                    type: 'echo',
                    interrupt: true,
                    sessionid: String(sessionid)
                })
            }).catch(e => WARN('echo error:', e));

            setTimeout(() => {
                sleepModel(false);
            }, 5500);
        }"""

assert old_approved_block in content, "old_approved_block not found"
content = content.replace(old_approved_block, new_approved_block, 1)

with open('web/avatar-experimental.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully applied speech payment flow updates!")
