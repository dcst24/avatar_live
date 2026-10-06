import re

html_path = 'web/avatar-experimental.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add _isLocationIntent and _isInfoIntent helpers around line 4580
helpers_code = """
        function _isLocationIntent(text) {
            const clean = text.toLowerCase().trim().replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g,"").trim();
            const locationKeywords = [
                'donde esta', 'donde queda', 'donde lo encuentro', 'donde encontrarlo',
                'en que pasillo', 'que pasillo', 'pasillo', 'ubicacion', 'donde se encuentra',
                'como llego', 'como llegar', 'en que piso', 'que piso', 'quiero saber donde esta',
                'quiero saber donde encontrarlo', 'ver ubicacion', 'mostrar en el mapa', 'mapa'
            ];
            return locationKeywords.some(w => clean.includes(w));
        }

        function _isInfoIntent(text) {
            const clean = text.toLowerCase().trim().replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g,"").trim();
            const infoKeywords = [
                'informacion', 'informacion adicional', 'saber informacion', 'mas informacion',
                'detalles', 'caracteristicas', 'que caracteristicas tiene', 'de que marca es',
                'marca', 'precio', 'cuanto cuesta', 'saber mas', 'cuentame mas'
            ];
            return infoKeywords.some(w => clean.includes(w));
        }
"""

if '_isLocationIntent' not in content:
    content = content.replace('function _isPayIntent(text) {', helpers_code + '\n        function _isPayIntent(text) {')

# 2. Update processUserSpeechInput around line 3340
old_speech_block = re.search(r'// 2\. Intercepción inmediata de afirmación de agregar al carrito.*?// 3\. Intercepción inmediata de rechazo a agregar al carrito.*?(?=if \(_isSleepWord\(question\)\))', content, re.DOTALL)
if old_speech_block:
    new_speech_block = """// 2. Manejo de intenciones tras escaneo de producto (_pendingCartProduct activo)
                    if (_pendingCartProduct && _pendingAction === 'CONFIRM_ADD_CART') {
                        const prod = _pendingCartProduct;

                        // A. El usuario pide UBICACIÓN ("dónde está", "dónde encontrarlo", etc.)
                        if (_isLocationIntent(question)) {
                            LOG(`[Scan Intent] Usuario solicitó ubicación de: ${prod.nombre}`);
                            setUserText(question, false);
                            addChatBubble('user', question);

                            const pisoStr = prod.piso ? `Piso ${prod.piso}` : 'Piso 1';
                            const pasilloStr = prod.pasillo ? `pasillo ${prod.pasillo}` : 'pasillo principal';
                            const sectorStr = prod.sector ? `sector ${prod.sector}` : 'tienda';
                            const locMsg = `El producto ${prod.nombre} se encuentra en el ${pisoStr}, ${pasilloStr}, ${sectorStr}. Te mostraré la ubicación en el mapa. ¿Deseas agregarlo a tu bolsa de compras?`;

                            queueAvatarBubble(locMsg);
                            stopAlwaysOnListening();
                            const sessionid = document.getElementById('sessionid').value;
                            fetch('/human', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ text: locMsg, type: 'echo', sessionid: String(sessionid) })
                            }).catch(e => WARN('echo error:', e));

                            // Abrir mapa interactivo
                            openMapForProduct(prod.sku || prod.codigo_barra);
                            return;
                        }

                        // B. El usuario pide INFORMACIÓN ADICIONAL ("características", "marca", "detalles")
                        if (_isInfoIntent(question)) {
                            LOG(`[Scan Intent] Usuario solicitó información adicional de: ${prod.nombre}`);
                            setUserText(question, false);
                            addChatBubble('user', question);

                            const precioReg = Number(prod.precio).toLocaleString('es-CL');
                            let infoMsg = `${prod.nombre} de marca ${prod.marca || 'Paris'}. `;
                            if (prod.oferta === 'SI' && prod.precio_oferta) {
                                const precioOf = Number(prod.precio_oferta).toLocaleString('es-CL');
                                const dcto = prod.descuento_pct ? ` con ${prod.descuento_pct} por ciento de descuento` : '';
                                infoMsg += `En oferta a ${precioOf} pesos${dcto} (antes ${precioReg} pesos). `;
                            } else {
                                infoMsg += `Su precio regular es de ${precioReg} pesos. `;
                            }
                            if (prod.categoria) {
                                infoMsg += `Categoría ${prod.categoria}. `;
                            }
                            infoMsg += `¿Deseas agregarlo a tu bolsa de compras?`;

                            queueAvatarBubble(infoMsg);
                            stopAlwaysOnListening();
                            const sessionid = document.getElementById('sessionid').value;
                            fetch('/human', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ text: infoMsg, type: 'echo', sessionid: String(sessionid) })
                            }).catch(e => WARN('echo error:', e));
                            return;
                        }

                        // C. El usuario responde AFIRMATIVAMENTE ("sí", "agrégalo", "al carrito", "cómpralo")
                        if (_isAffirmativeWord(question)) {
                            LOG(`[Scan Intent] Confirmación afirmativa de agregar al carrito: ${prod.nombre}`);
                            _pendingAction = null;
                            _pendingCartProduct = null;
                            addToCart(prod);

                            const count = getCartItemsCount();
                            const total = getCartTotal();
                            const ackMsg = `Listo, agregué ${prod.nombre} a tu bolsa. Llevas ${count} ${count === 1 ? 'producto' : 'productos'} por ${total.toLocaleString('es-CL')} pesos. ¿Vamos a la caja a pagar o deseas ver algo más?`;

                            setUserText(question, false);
                            addChatBubble('user', question);
                            queueAvatarBubble(ackMsg);
                            stopAlwaysOnListening();
                            const sessionid = document.getElementById('sessionid').value;
                            fetch('/human', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ text: ackMsg, type: 'echo', sessionid: String(sessionid) })
                            }).catch(e => WARN('echo error:', e));
                            return;
                        }

                        // D. El usuario responde NEGATIVAMENTE ("no", "no gracias")
                        if (_isNegativeWord(question)) {
                            LOG(`[Scan Intent] Rechazo de compra: ${prod.nombre}`);
                            _pendingAction = null;
                            _pendingCartProduct = null;
                            const noMsg = "Entendido, no lo agregaré. ¿Te gustaría buscar algún otro producto o necesitas ayuda?";

                            setUserText(question, false);
                            addChatBubble('user', question);
                            queueAvatarBubble(noMsg);
                            stopAlwaysOnListening();
                            const sessionid = document.getElementById('sessionid').value;
                            fetch('/human', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ text: noMsg, type: 'echo', sessionid: String(sessionid) })
                            }).catch(e => WARN('echo error:', e));
                            return;
                        }
                    }

                    """
    content = content.replace(old_speech_block.group(0), new_speech_block, 1)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Part 2: Location/Info/Affirmative/Negative speech handling updated successfully.")
