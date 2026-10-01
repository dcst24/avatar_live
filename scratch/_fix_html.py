import os, re

WEB = r"C:\Users\tom\Desktop\Proyectos\avatar_live\web"
FILES = ["avatar.html","avatar-experimental.html","avatar-general.html",
         "avatar-experimental-pendon.html","avatar-experimental-pendon-2.html"]

P1_OLD = "isCharging: false,\n            activeTransaction: null,"
P1_NEW = "isCharging: false,\n            isCancelling: false,\n            activeTransaction: null,"

P2_OLD_RE = r"function cancelGetnetTransaction\(\) \{.*?setTimeout\(\(\) =>\s*\{\s*closePosSimulator\(\);\s*\},\s*1000\);\s*\}"
P2_NEW = """function cancelGetnetTransaction() {
            appendPosLog("Cancelando transaccion activa en POS Getnet...", "warn");
            posState.isCancelling = true;
            posState.isCharging = false;
            try { if (typeof Getnet !== 'undefined') { Getnet.CancelSale(); } } catch (e) {}
            const instruction = document.getElementById('pos-instruction-text');
            if (instruction) instruction.textContent = "Cancelando en el terminal POS...";
            const livePill = document.getElementById('pos-live-pill');
            if (livePill) { livePill.className = 'pos-status-chip offline'; livePill.textContent = 'CANCELADO'; }
            setTimeout(() => { posState.isCancelling = false; closePosSimulator(); }, 2000);
        }"""

P3_OLD_RE = r"async function handleGetnetCallback\(msg\) \{.*?\n        \}"

P3_NEW = """async function handleGetnetCallback(msg) {
            if (!msg) return;
            let data = msg;
            if (msg.JsonSerialized && typeof msg.JsonSerialized === 'string') {
                try { const inner = JSON.parse(msg.JsonSerialized); data = { ...msg, ...inner }; } catch (e) {}
            }
            console.log("[Getnet CB] Cmd:" + (data.Command??'-') + " RC:" + (data.ResponseCode??'-') + " | charging:" + posState.isCharging + " cancelling:" + posState.isCancelling, data);
            appendPosLog("<<< POS [Cmd:" + (data.Command??'-') + " RC:" + (data.ResponseCode??'-') + "]: " + JSON.stringify(data), 'info');
            const instruction = document.getElementById('pos-instruction-text');
            const subinstruction = document.getElementById('pos-subinstruction-text');
            const livePill = document.getElementById('pos-live-pill');
            if (data.Received === true) {
                appendPosLog("ACK recibido del POS Getnet.", "info");
                if (instruction) instruction.textContent = "Acerque tarjeta, inserte chip o digite PIN en el POS";
                if (subinstruction) subinstruction.textContent = "Siga las instrucciones en la pantalla del terminal...";
                return;
            }
            if (data.Command === 106) {
                appendPosLog("Poll exitoso: POS Getnet respondiendo.", "success");
                if (livePill && !posState.isCharging) { livePill.className = 'pos-status-chip online'; livePill.textContent = 'EN LINEA'; }
                return;
            }
            if (data.Command === 116) {
                appendPosLog("Confirmacion de cancelacion recibida del POS.", "warn");
                posState.isCancelling = false;
                posState.isCharging = false;
                return;
            }
            if (posState.isCancelling) {
                console.warn("[Getnet POS] Respuesta ignorada: cancelacion activa desde la web.", data);
                appendPosLog("Respuesta del POS ignorada (cancelacion activa desde la web).", "warn");
                posState.isCharging = false;
                return;
            }
            const isSaleCommand = data.Command === 100 || data.Command === undefined || data.Command === null;
            if (isSaleCommand && !data.ResponseCode && !data.AuthorizationCode && data.Message) {
                appendPosLog("[POS Estado]: " + data.Message, "info");
                if (instruction) instruction.textContent = data.Message;
                if (subinstruction) subinstruction.textContent = "Terminal POS Getnet en proceso...";
                return;
            }
            const hasFinalResult = isSaleCommand && (
                data.ResponseCode !== undefined ||
                data.AuthorizationCode !== undefined ||
                (data.SharesNumber !== undefined && data.Amount !== undefined)
            );
            if (hasFinalResult) {
                if (!posState.isCharging) {
                    console.log("[Getnet POS] Ignorando mensaje residual fuera de cobro activo:", data);
                    return;
                }
                posState.isCharging = false;
                posState.isCancelling = false;
                posState.lastPaidTime = Date.now();
                const rcRaw = data.ResponseCode;
                const respCode = rcRaw !== undefined ? Number(rcRaw) : -1;
                const hasExplicitApproval = respCode === 0 && !!(data.AuthorizationCode || data.Amount);
                console.log("[Getnet POS] Resultado final: RC=" + respCode + " hasApproval=" + hasExplicitApproval);
                if (hasExplicitApproval) {
                    const authCode = data.AuthorizationCode || ("GET-" + Math.floor(100000 + Math.random()*900000));
                    appendPosLog("PAGO APROBADO EN POS GETNET! Auth: " + authCode, 'success');
                    if (instruction) instruction.textContent = "Pago Aprobado con Exito!";
                    if (subinstruction) subinstruction.textContent = "Generando comprobante digital...";
                    if (livePill) { livePill.className = 'pos-status-chip online'; livePill.textContent = 'APROBADO'; }
                    const tx = posState.activeTransaction || {};
                    const payload = {
                        plan_id: tx.plan ? tx.plan.id : 'plan_1m',
                        plan_nombre: tx.plan ? tx.plan.nombre : 'Plan Gimnasio',
                        banco: tx.bankName || 'Banco Santander',
                        es_santander: tx.isSantander || false,
                        cuotas: data.SharesNumber ? Number(data.SharesNumber) : (tx.cuotas || 1),
                        monto_pagado: data.Amount ? Number(data.Amount) : (tx.amount || 27990),
                        monto_original: tx.originalAmount || tx.amount,
                        descuento: tx.discount || 0,
                        rut: tx.rut || gymState.client.rut || '12.345.678-5',
                        nombre: tx.clientName || gymState.client.nombre || 'Socio FitLife',
                        email: tx.clientEmail || gymState.client.email || 'cliente@correo.cl',
                        codigo_autorizacion: authCode,
                        codigo_operacion: data.OperationNumber || data.TicketNumber || tx.ticketNumber || ("OP-" + Math.floor(100000 + Math.random()*900000)),
                        card_number: data.CardNumber || data.Pan || '**** **** **** ****',
                        card_brand: data.CardBrand || data.CardType || (tx.isSantander ? 'SANTANDER VISA' : 'TARJETA BANCARIA')
                    };
                    try {
                        fetch('/api/gym/pago/registrar', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
                        }).then(function(r) { return r.json(); }).then(function(json) {
                            closePosSimulator();
                            if (json && json.code === 0 && json.data) { showVoucher(json.data); } else { showVoucher(payload); }
                        }).catch(function() { closePosSimulator(); showVoucher(payload); });
                    } catch (e) { console.error("Error registrando pago:", e); closePosSimulator(); showVoucher(payload); }
                } else {
                    const desc = data.ResponseDescription || data.Message || (respCode === -1 ? "Respuesta desconocida del POS" : "Transaccion no autorizada o cancelada en el POS");
                    appendPosLog("Transaccion rechazada/cancelada: [RC:" + respCode + "] " + desc, 'error');
                    if (instruction) instruction.textContent = respCode === -1 ? "Respuesta inesperada del POS" : ("Cobro Rechazado: " + desc);
                    if (subinstruction) subinstruction.textContent = "Puedes intentar nuevamente o seleccionar otro medio de pago.";
                    if (livePill) { livePill.className = 'pos-status-chip offline'; livePill.textContent = respCode === -1 ? 'ERROR' : 'RECHAZADO'; }
                }
            }
        }"""

for fname in FILES:
    path = os.path.join(WEB, fname)
    if not os.path.exists(path):
        print("SKIP: " + fname); continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    original = content
    applied = []
    if P1_OLD in content:
        content = content.replace(P1_OLD, P1_NEW, 1); applied.append("P1")
    m2 = re.search(P2_OLD_RE, content, re.DOTALL)
    if m2:
        content = content[:m2.start()] + P2_NEW + content[m2.end():]; applied.append("P2")
    m3 = re.search(P3_OLD_RE, content, re.DOTALL)
    if m3 and ("hasFinalResult" in m3.group(0) or "isCharging" in m3.group(0)):
        content = content[:m3.start()] + P3_NEW + content[m3.end():]; applied.append("P3")
    elif not m3:
        print("  WARN P3 no encontrado: " + fname)
    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("OK " + fname + ": " + str(applied))
    else:
        print("NOOP " + fname)
print("Done.")
