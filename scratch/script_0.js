
        // ══════════════════════════════════════════════════════════════════════════════
        // DEBUG LOGGER — escribe en consola del navegador Y en el panel on-screen 🪲
        // ══════════════════════════════════════════════════════════════════════════════
        const _DBG_MAX = 200;

        function _dbgWrite(level, args) {
            if (level === 'log') console.log('[Avatar]', ...args);
            if (level === 'warn') console.warn('[Avatar]', ...args);
            if (level === 'err') console.error('[Avatar]', ...args);

            const list = document.getElementById('dbg-list');
            if (!list) return;

            const now = new Date();
            const ts = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.${String(now.getMilliseconds()).padStart(3, '0')}`;
            const msg = args.map(a => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ');

            const entry = document.createElement('div');
            entry.className = `dbg-entry dbg-${level}`;
            entry.innerHTML =
                `<span class="dbg-ts">${ts}</span>` +
                `<span class="dbg-label-${level}">${level.toUpperCase()}</span>` +
                `<span class="dbg-msg">${msg.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>`;
            list.appendChild(entry);

            while (list.children.length > _DBG_MAX) list.removeChild(list.firstChild);

            const panel = document.getElementById('dbg-panel');
            if (panel && panel.classList.contains('open')) {
                list.scrollTop = list.scrollHeight;
            }
        }

        const LOG = (...args) => _dbgWrite('log', args);
        const WARN = (...args) => _dbgWrite('warn', args);
        const ERR = (...args) => _dbgWrite('err', args);

        function dbgToggle() {
            const panel = document.getElementById('dbg-panel');
            panel.classList.toggle('open');
            if (panel.classList.contains('open')) {
                const list = document.getElementById('dbg-list');
                list.scrollTop = list.scrollHeight;
            }
        }

        function dbgClear() {
            const list = document.getElementById('dbg-list');
            list.innerHTML = '';
            LOG('Consola limpiada');
        }

        // ─── Selector de micrófono en panel debug ─────────────────────────────────
        let _preferredDeviceId = null;

        async function dbgLoadDevices() {
            const sel = document.getElementById('dbg-mic-select');
            if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
                WARN('enumerateDevices no disponible en este dispositivo');
                return;
            }
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const audioInputs = devices.filter(d => d.kind === 'audioinput');
                LOG(`Micrófonos disponibles: ${audioInputs.length}`);
                audioInputs.forEach((d, i) => {
                    LOG(`  [${i}] id="${d.deviceId.slice(0, 16)}…" label="${d.label || '(sin permiso)'}"`);
                });

                if (sel) {
                    sel.innerHTML = '<option value="">-- default del sistema --</option>';
                    audioInputs.forEach((d, i) => {
                        const opt = document.createElement('option');
                        opt.value = d.deviceId;
                        opt.textContent = d.label
                            ? d.label
                            : `Micrófono ${i + 1}  (${d.deviceId.slice(0, 8)}…)`;
                        if (d.deviceId === _preferredDeviceId) opt.selected = true;
                        sel.appendChild(opt);
                    });
                }

                if (audioInputs.length === 0) ERR('¡No se encontraron micrófonos!');
            } catch (e) {
                ERR('dbgLoadDevices error:', e.name, e.message);
            }
        }

        function dbgSelectMic(deviceId) {
            _preferredDeviceId = deviceId || null;
            if (_preferredDeviceId) {
                const sel = document.getElementById('dbg-mic-select');
                const label = sel?.options[sel.selectedIndex]?.textContent || deviceId;
                LOG(`🎤 Micrófono seleccionado: "${label}"`);
            } else {
                LOG('🎤 Micrófono: default del sistema');
            }
        }

        LOG('=== INIT ===');
        LOG('UA:', navigator.userAgent);
        LOG('Secure context:', window.isSecureContext);
        LOG('SpeechRecognition:', !!(window.SpeechRecognition || window.webkitSpeechRecognition));
        LOG('getUserMedia:', !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia));
        LOG('Protocol:', location.protocol, '| Host:', location.host);

        // ─── Estado ────────────────────────────────────────────────────────────────
        let isConnected = false;
        let isListening = false;
        let recognition = null;
        let isSpeaking = false;
        let speakCheckInterval = null;
        let _audioUnlocked = false;

        // ─── Wake-word & Modo Conversación Abierta (Experimental) ───────────────
        const WAKE_WORDS = ['hola', 'oye', 'disculpa', 'permiso', 'necesito ayuda', 'asistente', 'buenas'];
        const WAKE_WORD = WAKE_WORDS[0];

        let _wakeDetected = false;
        let _alwaysOnActive = false;

        let _conversationAwake = false;  // true si el flujo de conversación está activo sin requerir wake-word
        let _inactivityTimeoutId = null; // temporizador de inactividad
        let _followUpTimeoutId = null;   // ID del temporizador para preguntar si necesita algo más
        let _waitingFollowUpAck = false;  // true cuando se preguntó "¿Necesitas algo más?" y esperamos respuesta
        let _followUpAckTimeoutId = null; // timer del segundo wait de 30s tras "¿Necesitas algo más?"
        let _pendingAvatarBubbleText = null;    // Texto de respuesta del LLM en cola para mostrar cuando empiece a hablar
        let _pendingAvatarBubbleTimeout = null; // Timeout de seguridad para la burbuja en cola
        const INACTIVITY_TIMEOUT_MS = 120000;   // 2 minutos antes de volver a modo de espera

        const BUFFER_MS = 5000;                 // ms de espera para pregunta tras la wake-word
        let _wakeBufferTimeout = null;

        const WAKE_ONLY_GREETINGS = [
            '¡Hola! Bienvenido a Servipag. ¿Qué cuenta deseas pagar hoy?',
            '¡Hola! ¿En qué cuenta o servicio te puedo ayudar?',
            'Aquí estoy. ¿Qué cuenta deseas consultar o pagar hoy?',
            '¡Hola! Dime qué servicio o cuenta necesitas pagar.'
        ];

        function _randomGreeting() {
            return WAKE_ONLY_GREETINGS[Math.floor(Math.random() * WAKE_ONLY_GREETINGS.length)];
        }

        function _containsWakeWord(text) {
            const lower = text.toLowerCase();
            return WAKE_WORDS.some(w => lower.includes(w));
        }

        function _extractQuestion(text) {
            if (!text) return '';
            const lower = text.toLowerCase();
            let best = { idx: -1, word: '' };
            for (const w of WAKE_WORDS) {
                const i = lower.indexOf(w);
                if (i !== -1 && (best.idx === -1 || i < best.idx)) {
                    best = { idx: i, word: w };
                }
            }
            if (best.idx === -1) return text.trim();
            return text.slice(best.idx + best.word.length).replace(/^[,\.\s¿¡!?]+|[,\.\s¿¡!?]+$/g, '').trim();
        }

        function isWakeOnlyGreeting(text) {
            if (!text) return false;
            const clean = text.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g, "").trim();
            const commonGreetings = [
                'hola', 'buenas', 'buen dia', 'buenos dias', 'buenas tardes', 'buenas noches',
                'hola buenas', 'hola buenos dias', 'hola buen dia', 'oye', 'disculpa', 'permiso', 'asistente'
            ];
            if (commonGreetings.includes(clean)) return true;
            const q = _extractQuestion(text);
            const cleanQ = q.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g, "").trim();
            return !cleanQ || commonGreetings.includes(cleanQ);
        }

        function _isSleepWord(text) {
            const clean = text.toLowerCase().trim().replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g,"").trim();
            // Frases exactas de despedida o cierre negativo
            const exactSleepPhrases = [
                'no', 'no gracias', 'no muchas gracias', 'no por ahora', 'no nada mas',
                'no ya no', 'no seria todo', 'no eso seria todo', 'no eso es todo',
                'no por el momento', 'no de momento', 'no gracias chao',
                'gracias', 'muchas gracias', 'chao', 'adios', 'hasta luego',
                'nada mas', 'ninguna', 'ninguno', 'eso es todo', 'nos vemos',
                'que estes bien', 'chao chao', 'bye', 'seria todo', 'listo gracias'
            ];
            if (exactSleepPhrases.includes(clean)) {
                return true;
            }

            // Prefijos de despedida explícita (NUNCA incluir 'no' aquí para no cortar frases como 'no hay este producto')
            const farewellPrefixes = [
                'chao ', 'adios ', 'hasta luego ', 'nos vemos ', 'bye ', 'muchas gracias ', 'gracias por '
            ];
            if (farewellPrefixes.some(pre => clean.startsWith(pre))) {
                return true;
            }

            return false;
        }

        function clearServerHistory() {
            const sessionid = document.getElementById('sessionid').value;
            LOG('Borrando historial de conversación en servidor para sesión:', sessionid);
            fetch('/clear_history', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sessionid: String(sessionid) })
            }).catch(e => WARN('clearServerHistory error:', e));
        }

        function sleepModel(showBubble = false) {
            LOG("Durmiendo el modelo experimental (conversación cerrada).");
            _conversationAwake = false;
            _wakeDetected = false;
            _waitingFollowUpAck = false;
            clearTimeout(_inactivityTimeoutId);
            clearTimeout(_followUpTimeoutId);
            clearTimeout(_followUpAckTimeoutId);
            if (typeof _postPaymentFollowUpSafetyTimeout !== 'undefined') {
                clearTimeout(_postPaymentFollowUpSafetyTimeout);
            }
            if (typeof _pendingReceiptFollowUp !== 'undefined') {
                _pendingReceiptFollowUp = false;
            }
            clearServerHistory();

            // Cerrar tabla de cuentas, carro, numpad y vaciar carro
            hideAccountsPanel();
            closeCart();
            hideRutNumpad();
            _cart = [];
            updateCartUI();

            setState('listening', 'Esperando activación…');
            if (showBubble) {
                addChatBubble('system', 'Conversación finalizada. Di "Hola" para activar de nuevo.');
            }
        }

        function wakeUpModel() {
            if (!_conversationAwake) {
                LOG("Despertando el modelo experimental (conversación abierta).");
                _conversationAwake = true;
                const container = document.getElementById('chat-container');
                if (container) container.innerHTML = '';
            }
            resetInactivityTimer();
        }

        function resetInactivityTimer() {
            clearTimeout(_inactivityTimeoutId);
            if (!_conversationAwake) return;
            _inactivityTimeoutId = setTimeout(() => {
                LOG("Sesión inactiva por 2 minutos. Volviendo a modo de espera de wake-word.");
                sleepModel(true);
            }, INACTIVITY_TIMEOUT_MS);
        }

        function normalizarTexto(text) {
            if (!text) return '';
            return text
                .replace(/(\d+)\s*%/g, '$1 por ciento')
                .replace(/\$(\d[\d\.]*)\s*(?:pesos)?/g, '$1 pesos')
                .replace(/[→⇒➜➞➝➔]|->|=>|<-|<=|↔/g, ' ')
                .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
                .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
                .replace(/~~([^~]+)~~/g, '$1')
                .replace(/`+([^`]+)`+/g, '$1')
                .replace(/^\s*#{1,6}\s*/gm, '')
                .replace(/[-—–]+/g, ' ')
                .replace(/[*#|_\\/\[\]{}~^<>•·●○■◆▪\(\)]/g, ' ')
                .replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]/g, '')
                .replace(/\s+([,.:;?!])/g, '$1')
                .replace(/[,]{2,}/g, ',')
                .replace(/[.]{2,}/g, '.')
                .replace(/\s{2,}/g, ' ')
                .replace(/\b[Rr][Uu][Tt]\b/g, 'rut')
                .trim();
        }

        const SPANISH_NUMS = {
            'cero': 0, 'un': 1, 'uno': 1, 'una': 1,
            'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
            'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9,
            'diez': 10, 'once': 11, 'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15,
            'dieciseis': 16, 'dieciséis': 16, 'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19,
            'veinte': 20, 'veintiuno': 21, 'veintidos': 22, 'veintidós': 22, 'veintitres': 23, 'veintitrés': 23,
            'veinticuatro': 24, 'veinticinco': 25, 'veintiseis': 26, 'veintiséis': 26, 'veintisiete': 27,
            'veintiocho': 28, 'veintinueve': 29,
            'treinta': 30, 'cuarenta': 40, 'cincuenta': 50,
            'sesenta': 60, 'setenta': 70, 'ochenta': 80, 'noventa': 90,
            'cien': 100, 'ciento': 100, 'doscientos': 200, 'trescientos': 300,
            'cuatrocientos': 400, 'quinientos': 500, 'seiscientos': 600,
            'setecientos': 700, 'ochocientos': 800, 'novecientos': 900
        };

        function parseSpokenSpanishNumbers(text) {
            if (!text) return '';
            const tokens = text.match(/[a-zA-ZáéíóúÁÉÍÓÚñÑ]+|\d+|[-]|[,.:;?!¿¡]/g) || [];
            const result = [];
            let i = 0;
            const n = tokens.length;
            while (i < n) {
                const tok = tokens[i];
                const tokLower = tok.toLowerCase();
                if (SPANISH_NUMS[tokLower] !== undefined && SPANISH_NUMS[tokLower] >= 100 && i + 1 < n && SPANISH_NUMS[tokens[i+1].toLowerCase()] !== undefined) {
                    let val = SPANISH_NUMS[tokLower];
                    i++;
                    if (i + 2 < n && SPANISH_NUMS[tokens[i].toLowerCase()] !== undefined && tokens[i+1].toLowerCase() === 'y' && SPANISH_NUMS[tokens[i+2].toLowerCase()] !== undefined) {
                        val += SPANISH_NUMS[tokens[i].toLowerCase()] + SPANISH_NUMS[tokens[i+2].toLowerCase()];
                        i += 3;
                    } else if (SPANISH_NUMS[tokens[i].toLowerCase()] !== undefined) {
                        val += SPANISH_NUMS[tokens[i].toLowerCase()];
                        i++;
                    }
                    result.push(String(val));
                } else if (SPANISH_NUMS[tokLower] !== undefined && i + 2 < n && tokens[i+1].toLowerCase() === 'y' && SPANISH_NUMS[tokens[i+2].toLowerCase()] !== undefined) {
                    const val = SPANISH_NUMS[tokLower] + SPANISH_NUMS[tokens[i+2].toLowerCase()];
                    result.push(String(val));
                    i += 3;
                } else if (SPANISH_NUMS[tokLower] !== undefined) {
                    result.push(String(SPANISH_NUMS[tokLower]));
                    i++;
                } else if (['k', 'ka', 'ca'].includes(tokLower) && (i > 0 && (['guion', 'guión', 'raya', 'menos', '-'].includes(tokens[i-1].toLowerCase()) || (result.length > 0 && (/\d+/.test(result[result.length - 1]) || result[result.length - 1] === '-'))))) {
                    result.push('K');
                    i++;
                } else if (['guion', 'guión', 'raya', 'menos'].includes(tokLower)) {
                    result.push('-');
                    i++;
                } else if (['millon', 'millones', 'mil'].includes(tokLower) && result.length > 0 && /\d+/.test(result[result.length - 1])) {
                    i++;
                } else if (/^\d+$/.test(tok) || tok === '-') {
                    result.push(tok);
                    i++;
                } else {
                    result.push(tok);
                    i++;
                }
            }

            let s = result.join(' ');
            s = s.replace(/\s+([,.:;?!])/g, '$1');
            s = s.replace(/([¿¡])\s+/g, '$1');
            // Colapsar puntos y comas entre dígitos (ej: '12. 345. 678' -> '12345678')
            s = s.replace(/(?<=\d)\s*[\.,]\s*(?=\d)/g, '');
            s = s.replace(/(?<=\d)\s+(?=[\dkK]\b)/gi, '');
            s = s.replace(/\s*-\s*/g, '-');
            s = s.replace(/(?<=\d)\s+(?=\d)/g, '');
            s = s.replace(/(\d+)-([\dkK])\b/gi, '$1-$2');
            return s;
        }

        function normalizeUserInput(text) {
            if (!text) return '';
            let s = text.trim();

            // 1. Normalizar Enel si STT transcribió 'En', 'en el', 'en él', 'ener', 'ene'
            s = s.replace(/^(?:en|en\s+el|en\s+él|ene|ener)$/i, 'Enel');
            s = s.replace(/\b(?:empresa|cuenta|para|de)\s+(?:en\s+el|en\s+él|ener|ene|en)\b/gi, (m) => m.split(/\s+/)[0] + ' Enel');
            s = s.replace(/\b(?:en\s+el|en\s+él|ener|ene)\b/gi, 'Enel');
            s = s.replace(/\ben\s*,\s*/gi, 'Enel, ');
            s = s.replace(/\ben\s+(?=rut|cliente|número|numero|\d)/gi, 'Enel ');

            // 2. Parsear números hablados en palabras españolas a dígitos
            s = parseSpokenSpanishNumbers(s);

            // 3. Colapsar puntos y comas entre dígitos (cuando STT pone pausas tipo '12, 345, 678-5' o '12. 345. 678-5')
            s = s.replace(/(?<=\d)\s*[\.,]\s*(?=\d)/g, '');

            // 4. Normalizar guion y espacios alrededor
            s = s.replace(/\s*(?:-|guion|guión|raya|menos)\s*/gi, '-');

            // 5. Colapsar espacios entre dígitos consecutivos (ej: '1 2 3 4 5 6 7 8 - 5' -> '12345678-5')
            s = s.replace(/(?<=\d)\s+(?=[\dkK]\b)/gi, '');
            s = s.replace(/(?<=\d)\s+(?=\d)/g, '');

            // 6. Asegurar formato RUT con guión
            s = s.replace(/(\d+)-([\dkK])\b/gi, '$1-$2');

            return s;
        }

        const _RUT_NUM_ALLOWED_TOKENS = new Set([
            '0','1','2','3','4','5','6','7','8','9','-','k','ka',
            'cero','un','uno','una','dos','tres','cuatro','cinco','seis','siete','ocho','nueve',
            'diez','once','doce','trece','catorce','quince','dieciseis','dieciséis','diecisiete',
            'dieciocho','diecinueve','veinte','veintiuno','veintidos','veintidós','veintitres',
            'veintitrés','veinticuatro','veinticinco','veintiseis','veintiséis','veintisiete',
            'veintiocho','veintinueve','treinta','cuarenta','cincuenta','sesenta','setenta',
            'ochenta','noventa','cien','ciento','cientos','doscientos','trescientos','cuatrocientos',
            'quinientos','seiscientos','setecientos','ochocientos','novecientos','mil','millon',
            'millones','y','con','guion','guión','raya','menos','barra','rut','el','mi','es'
        ]);

        function isPureNumberOrRutDictation(text) {
            if (!text) return false;
            const clean = text.toLowerCase()
                .replace(/[\.,\/#!$%\^&\*;:{}=_`~()¿?¡!]/g, ' ')
                .replace(/-/g, ' - ')
                .trim();
            const words = clean.split(/\s+/).filter(Boolean);
            if (words.length === 0) return false;

            let hasNumberOrRut = false;
            for (const w of words) {
                if (/^\d+$/.test(w) || _RUT_NUM_ALLOWED_TOKENS.has(w)) {
                    if (/^\d+$/.test(w) || (w !== 'el' && w !== 'mi' && w !== 'es' && w !== 'y' && w !== 'con')) {
                        hasNumberOrRut = true;
                    }
                } else {
                    return false; // Contiene palabras no numéricas / conversacionales
                }
            }
            return hasNumberOrRut;
        }

        function hasCompleteRut(text) {
            if (!text) return false;
            const norm = normalizeUserInput(text);
            return /\b\d{7,8}-?[\dkK]\b/.test(norm);
        }

        function addChatBubble(role, text) {
            const container = document.getElementById('chat-container');
            if (!container) return;

            const cleanText = (role === 'avatar') ? normalizarTexto(text) : text;

            // Evitar duplicar burbujas de sistema consecutivas idénticas
            if (role === 'system' && container.lastElementChild && container.lastElementChild.textContent.trim() === text.trim()) {
                return container.lastElementChild;
            }

            const bubble = document.createElement('div');
            bubble.className = `chat-bubble ${role}`;
            bubble.textContent = cleanText;
            container.appendChild(bubble);

            container.scrollTop = container.scrollHeight;

            while (container.children.length > 5) {
                container.removeChild(container.firstChild);
            }

            setTimeout(() => {
                bubble.classList.add('fade-out');
                setTimeout(() => {
                    if (bubble.parentNode) {
                        bubble.parentNode.removeChild(bubble);
                    }
                }, 500);
            }, 30000);

            return bubble;
        }

        function queueAvatarBubble(text) {
            clearTimeout(_pendingAvatarBubbleTimeout);
            _pendingAvatarBubbleText = text;
            
            if (isSpeaking) {
                addChatBubble('avatar', _pendingAvatarBubbleText);
                _pendingAvatarBubbleText = null;
                return;
            }
            
            _pendingAvatarBubbleTimeout = setTimeout(() => {
                if (_pendingAvatarBubbleText) {
                    addChatBubble('avatar', _pendingAvatarBubbleText);
                    _pendingAvatarBubbleText = null;
                }
            }, 4000);
        }

        function cancelFollowUpTimers(keepWaitingAck = false) {
            if (_followUpTimeoutId) {
                clearTimeout(_followUpTimeoutId);
                _followUpTimeoutId = null;
            }
            if (_followUpAckTimeoutId) {
                clearTimeout(_followUpAckTimeoutId);
                _followUpAckTimeoutId = null;
            }
            if (!keepWaitingAck) {
                _waitingFollowUpAck = false;
            }
        }

        function notifyUserActivity(actionName = '') {
            if (actionName) LOG(`[Actividad Usuario: ${actionName}] Cancelando/reiniciando timers de inactividad`);
            cancelFollowUpTimers(false);
            resetInactivityTimer();
        }

        function scheduleFollowUp() {
            // Cancelar cualquier timer previo de follow-up
            cancelFollowUpTimers(true);

            // Si la conversación no está activa, o si el avatar está hablando, o si se procesa pago, NO programar
            if (!_conversationAwake || isSpeaking || _isPaying) {
                LOG(`scheduleFollowUp: omitido (awake=${_conversationAwake}, isSpeaking=${isSpeaking}, isPaying=${_isPaying})`);
                return;
            }

            // Si ya estamos esperando ACK del follow-up, reprogramar únicamente el timeout de despedida
            if (_waitingFollowUpAck) {
                LOG('scheduleFollowUp: esperando ACK del follow-up, armando timeout de despedida.');
                scheduleFollowUpAckTimeout();
                return;
            }

            LOG('scheduleFollowUp: programando pregunta "¿Necesitas algo más?" en 15s de silencio');
            _followUpTimeoutId = setTimeout(() => {
                // Verificaciones estrictas antes de disparar la pregunta:
                if (!_conversationAwake || isSpeaking || _isPaying) {
                    LOG('scheduleFollowUp: descartado en ejecución porque el avatar está hablando o pagando.');
                    return;
                }

                // Si el usuario tiene el teclado numérico de RUT abierto o ha digitado dígitos, posponer
                const numpadOverlay = document.getElementById('rut-numpad-overlay');
                if ((numpadOverlay && numpadOverlay.classList.contains('open')) || (_rutBuffer && _rutBuffer.length > 0)) {
                    LOG('scheduleFollowUp: pospuesto porque el usuario está interactuando con el RUT.');
                    scheduleFollowUp();
                    return;
                }

                // Si el carro está abierto
                if (_cartOpen) {
                    LOG('scheduleFollowUp: pospuesto porque el carro está abierto.');
                    scheduleFollowUp();
                    return;
                }

                LOG("15 segundos de silencio sin interacción → Preguntando si necesita algo más.");
                const followUpText = "¿Necesitas algo más?";
                _waitingFollowUpAck = true;

                queueAvatarBubble(followUpText);
                stopAlwaysOnListening();

                const sessionid = document.getElementById('sessionid').value;
                fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: followUpText,
                        type: 'echo',
                        sessionid: String(sessionid)
                    })
                }).catch(e => WARN('Error al enviar follow-up:', e));
            }, 15000);
        }

        function scheduleFollowUpAckTimeout() {
            if (_followUpAckTimeoutId) {
                clearTimeout(_followUpAckTimeoutId);
                _followUpAckTimeoutId = null;
            }
            if (!_waitingFollowUpAck || !_conversationAwake) return;
            LOG('scheduleFollowUpAckTimeout: esperando 15s respuesta al follow-up…');
            _followUpAckTimeoutId = setTimeout(() => {
                if (!_waitingFollowUpAck || !_conversationAwake || isSpeaking || _isPaying) {
                    LOG('scheduleFollowUpAckTimeout: descartado porque el estado cambió.');
                    return;
                }

                const numpadOverlay = document.getElementById('rut-numpad-overlay');
                if ((numpadOverlay && numpadOverlay.classList.contains('open')) || (_rutBuffer && _rutBuffer.length > 0) || _cartOpen) {
                    LOG('scheduleFollowUpAckTimeout: usuario activo, cancelando despedida.');
                    _waitingFollowUpAck = false;
                    scheduleFollowUp();
                    return;
                }

                LOG('15s sin respuesta al follow-up → enviando despedida final y durmiendo.');
                _waitingFollowUpAck = false;
                const farewellText = "Muy bien, si necesitas algo más no dudes en llamarme. ¡Que tengas un excelente día!";
                queueAvatarBubble(farewellText);
                stopAlwaysOnListening();
                clearServerHistory();
                _conversationAwake = false;
                _wakeDetected = false;
                clearTimeout(_inactivityTimeoutId);
                cancelFollowUpTimers(false);

                // Cerrar tabla de cuentas, carro, numpad y vaciar carro
                hideAccountsPanel();
                closeCart();
                hideRutNumpad();
                _cart = [];
                updateCartUI();

                const sessionid = document.getElementById('sessionid').value;
                fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: farewellText,
                        type: 'echo',
                        sessionid: String(sessionid)
                    })
                }).then(() => {
                    addChatBubble('system', 'Conversación finalizada. Di "Hola" para activar de nuevo.');
                    setState('listening', 'Esperando activación…');
                }).catch(e => WARN('Error al enviar despedida final:', e));
            }, 15000);
        }

        // ─── Teclado Numérico Touch en Pantalla para RUT (Servipag) ──────────────
        let _rutBuffer = '';
        let _pendingRutNumpadShow = false;
        let _isRutError = false;
        let _isWaitingRut = false;
        let _lastAvatarMessage = '';

        function formatRutDisplay(raw) {
            if (!raw) return '';
            const clean = raw.replace(/[^0-9kK]/g, '').toUpperCase();
            if (clean.length <= 1) return clean;
            if (clean.length >= 8) {
                const body = clean.slice(0, -1);
                const dv = clean.slice(-1);
                const formattedBody = body.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
                return `${formattedBody}-${dv}`;
            }
            return clean.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        }

        function updateNumpadDisplay() {
            const displayEl = document.getElementById('numpad-display');
            const submitBtn = document.getElementById('numpad-btn-submit');
            if (!displayEl) return;

            if (!_rutBuffer) {
                displayEl.textContent = 'Ej: 12.345.678-5';
                displayEl.classList.add('placeholder');
                if (submitBtn) submitBtn.disabled = true;
            } else {
                displayEl.textContent = formatRutDisplay(_rutBuffer);
                displayEl.classList.remove('placeholder');
                if (submitBtn) {
                    submitBtn.disabled = (_rutBuffer.length < 7);
                }
            }
        }

        function numpadPress(char) {
            notifyUserActivity('numpadPress');
            if (_rutBuffer.length >= 9) return;
            const upper = String(char).toUpperCase();
            if (upper === 'K') {
                if (_rutBuffer.length < 6 || _rutBuffer.includes('K')) return;
                _rutBuffer += 'K';
            } else if (/^\d$/.test(upper)) {
                if (_rutBuffer.includes('K')) return;
                _rutBuffer += upper;
            }
            updateNumpadDisplay();
        }

        function numpadBackspace() {
            notifyUserActivity('numpadBackspace');
            if (_rutBuffer.length > 0) {
                _rutBuffer = _rutBuffer.slice(0, -1);
                updateNumpadDisplay();
            }
        }

        function numpadClear() {
            notifyUserActivity('numpadClear');
            _rutBuffer = '';
            updateNumpadDisplay();
        }

        function showRutNumpad(clear = false) {
            notifyUserActivity('showRutNumpad');
            const overlay = document.getElementById('rut-numpad-overlay');
            if (!overlay) return;
            if (clear) {
                _rutBuffer = '';
            }
            updateNumpadDisplay();
            overlay.classList.add('open');
            LOG('showRutNumpad: Teclado numérico abierto en pantalla');
        }

        function hideRutNumpad() {
            const overlay = document.getElementById('rut-numpad-overlay');
            if (overlay) {
                overlay.classList.remove('open');
                LOG('hideRutNumpad: Teclado numérico cerrado');
            }
        }

        function toggleRutNumpad() {
            const overlay = document.getElementById('rut-numpad-overlay');
            if (!overlay) return;
            if (overlay.classList.contains('open')) {
                hideRutNumpad();
            } else {
                showRutNumpad(false);
            }
        }

        // ══════════════════════════════════════════════════════════════════════════
        // GESTOR VISUAL DE CUENTAS, CARRO DE PAGOS Y ANIMACIÓN DE PAGO (SERVIPAG)
        // ══════════════════════════════════════════════════════════════════════════
        let _currentRut = '';
        let _currentClient = null;
        let _currentAccounts = [];
        let _cart = [];
        let _servipagPanelOpen = false;
        let _cartOpen = false;
        let _isPaying = false;
        let _payCountdownInterval = null;

        async function loadAndShowAccounts(rut, showPanel = true) {
            if (!rut) return;
            const clean = String(rut).replace(/[^0-9kK]/g, '').toUpperCase();
            if (clean.length < 7) return;

            try {
                LOG(`loadAndShowAccounts: Consultando cuentas para RUT ${clean} (showPanel=${showPanel})`);
                const res = await fetch('/api/servipag/rut', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rut: clean })
                });
                const resp = await res.json();
                if (resp.code === 0 && resp.data && resp.data.cuentas) {
                    if (_currentRut && clean !== _currentRut) {
                        _cart = [];
                    }
                    _currentRut = clean;
                    _currentClient = resp.data;
                    _currentAccounts = resp.data.cuentas;
                    _isWaitingRut = false;
                    _pendingRutNumpadShow = false;
                    hideRutNumpad();
                    renderAccountsTable(resp.data);
                    if (showPanel) {
                        showAccountsPanel();
                    }
                    // Refrescar estado del botón del carro (se mostrará solo si ya tiene cuentas)
                    updateCartUI();
                    if (showPanel && _lastAvatarMessage) {
                        autoSelectAccountFromAvatarResponse(_lastAvatarMessage);
                    }
                } else {
                    LOG('loadAndShowAccounts: No se encontraron cuentas o error:', resp.msg);
                }
            } catch (e) {
                ERR('loadAndShowAccounts error:', e);
            }
        }

        function showAccountsPanel() {
            const panel = document.getElementById('servipag-accounts-panel');
            if (panel) {
                panel.classList.add('open');
                _servipagPanelOpen = true;
                LOG('showAccountsPanel: Panel de cuentas abierto');
            }
        }

        function hideAccountsPanel() {
            const panel = document.getElementById('servipag-accounts-panel');
            if (panel) {
                panel.classList.remove('open');
                _servipagPanelOpen = false;
                LOG('hideAccountsPanel: Panel de cuentas cerrado');
            }
        }

        function renderAccountsTable(clientData) {
            const nameEl = document.getElementById('accounts-client-name');
            const rutEl = document.getElementById('accounts-client-rut');
            const tbody = document.getElementById('accounts-table-body');
            if (!tbody) return;

            if (nameEl) nameEl.textContent = clientData.titular || 'Cuentas Registradas';
            if (rutEl) rutEl.textContent = `RUT: ${clientData.rut_formateado || clientData.rut}`;

            tbody.innerHTML = '';

            const getCategoryIcon = (cat) => {
                const c = String(cat).toLowerCase();
                if (c.includes('luz') || c.includes('electr')) return '💡';
                if (c.includes('agua')) return '💧';
                if (c.includes('internet') || c.includes('telecom') || c.includes('movil') || c.includes('celular') || c.includes('cable') || c.includes('wifi')) return '🌐';
                if (c.includes('gas')) return '🔥';
                if (c.includes('autopista') || c.includes('tag')) return '🚗';
                return '📄';
            };

            clientData.cuentas.forEach((acc, idx) => {
                const row = document.createElement('tr');
                const isInCart = _cart.some(item => item.id_cuenta === acc.id_cuenta);
                const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');

                row.className = 'account-row' + (isInCart ? ' in-cart' : '') + (isPaid ? ' row-paid' : '');
                row.id = `account-row-${acc.id_cuenta}`;

                // Color verde para cuentas al día/pagadas, Blanco para normales, Amarillo para vencidas
                let dateHtml = '';
                if (isPaid) {
                    dateHtml = '<span style="color: #4ade80; font-size:12px; font-weight:600;">✓ Al día</span>';
                } else if (acc.es_vencida) {
                    dateHtml = `<span class="acc-date-overdue">⚠️ ${acc.fecha_vencimiento}</span>`;
                } else {
                    dateHtml = `<span class="acc-date-normal">${acc.fecha_vencimiento || acc.fecha_vencimiento_natural || 'Sin vencimiento'}</span>`;
                }

                const actionBtnHtml = isPaid
                    ? `<button type="button" class="acc-btn-add paid-btn" title="Cuenta pagada y al día" style="background: rgba(74, 222, 128, 0.12); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); cursor: pointer;" onclick="event.stopPropagation(); sayViaAvatar('Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.');">✓</button>`
                    : `<button type="button" class="acc-btn-add ${isInCart ? 'added' : ''}" title="${isInCart ? 'En el carro' : 'Agregar al carro'}">${isInCart ? '✓' : '＋'}</button>`;

                row.innerHTML = `
                    <td style="text-align:center;">
                        <div class="acc-number-badge">${acc.numero || (idx + 1)}</div>
                    </td>
                    <td>
                        <div class="acc-service-badge">
                            <span>${getCategoryIcon(acc.categoria)}</span>
                            <span>${acc.categoria ? (acc.categoria.charAt(0).toUpperCase() + acc.categoria.slice(1)) : 'Servicio'}</span>
                        </div>
                    </td>
                    <td>
                        <div class="acc-company-title">${acc.empresa_nombre || acc.empresa_id}</div>
                    </td>
                    <td class="acc-amount">
                        ${isPaid ? '$0' : (acc.monto_formateado || ('$' + acc.monto))}
                    </td>
                    <td style="text-align:right;">
                        ${dateHtml}
                    </td>
                    <td style="text-align:center;">
                        ${actionBtnHtml}
                    </td>
                `;

                // Clic en la fila o botón: si está pagada, el avatar informa que ya está pagada; si no, agrega o quita del carro
                row.onclick = () => {
                    if (isPaid) {
                        sayViaAvatar(`Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.`);
                        return;
                    }
                    toggleAccountInCart(acc, true);
                };

                tbody.appendChild(row);
            });
        }

        async function toggleAccountInCart(acc, announceAvatar = false) {
            notifyUserActivity('toggleAccountInCart');
            const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');
            if (isPaid) {
                LOG(`[Carro] Bloqueado: intento de agregar cuenta pagada (${acc.empresa_nombre})`);
                const existingIdx = _cart.findIndex(item => item.id_cuenta === acc.id_cuenta);
                if (existingIdx >= 0) {
                    _cart.splice(existingIdx, 1);
                    updateCartUI();
                }
                if (announceAvatar) {
                    sayViaAvatar(`Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.`);
                }
                return false;
            }

            const existingIdx = _cart.findIndex(item => item.id_cuenta === acc.id_cuenta);
            if (existingIdx >= 0) {
                _cart.splice(existingIdx, 1);
                LOG(`Cuenta removida del carro: ${acc.empresa_nombre}`);
            } else {
                _cart.push(acc);
                LOG(`Cuenta agregada al carro: ${acc.empresa_nombre} (${acc.monto_formateado})`);
                if (announceAvatar) {
                    const promptText = `Agregué tu cuenta de ${acc.empresa_nombre} por ${acc.monto_formateado} al carro. ¿Deseas pagarla ahora o agregar más cuentas?`;
                    sayViaAvatar(promptText);
                }
            }
            updateCartUI();
            if (_currentClient) {
                renderAccountsTable(_currentClient);
            }
            return true;
        }

        function updateCartUI() {
            const count = _cart.length;
            const total = _cart.reduce((sum, item) => sum + (item.monto || 0), 0);
            const totalFmt = `$${total.toLocaleString('es-CL')}`;

            // Actualizar botón flotante (mostrar solo si hay elementos en el carro)
            const btnCart = document.getElementById('btn-floating-cart');
            const badge = document.getElementById('cart-floating-badge');
            if (badge) badge.textContent = count;
            if (btnCart) {
                btnCart.style.display = count > 0 ? 'flex' : 'none';
            }

            // Actualizar modal del carro
            const totalEl = document.getElementById('cart-total-amount');
            if (totalEl) totalEl.textContent = totalFmt;

            const itemsContainer = document.getElementById('cart-items-container');
            const btnPay = document.getElementById('cart-btn-submit-pay');
            if (btnPay) btnPay.disabled = (count === 0);

            if (itemsContainer) {
                if (count === 0) {
                    itemsContainer.innerHTML = '<div class="cart-empty-msg">Tu carro de pagos está vacío.<br>Selecciona una cuenta de la tabla para agregar.</div>';
                } else {
                    itemsContainer.innerHTML = '';
                    _cart.forEach((item, idx) => {
                        const div = document.createElement('div');
                        div.className = 'cart-item';
                        div.innerHTML = `
                            <div class="cart-item-info">
                                <span class="cart-item-name">${item.empresa_nombre}</span>
                                <span class="cart-item-sub">Cuenta N° ${item.identificador || item.id_cuenta}</span>
                            </div>
                            <div class="cart-item-right">
                                <span class="cart-item-price">${item.monto_formateado}</span>
                                <button type="button" class="cart-item-remove" onclick="event.stopPropagation(); removeCartItem(${idx});" title="Eliminar">✕</button>
                            </div>
                        `;
                        itemsContainer.appendChild(div);
                    });
                }
            }
        }

        function removeCartItem(idx) {
            notifyUserActivity('removeCartItem');
            if (idx >= 0 && idx < _cart.length) {
                _cart.splice(idx, 1);
                updateCartUI();
                if (_currentClient) renderAccountsTable(_currentClient);
            }
        }

        function toggleCart() {
            const overlay = document.getElementById('servipag-cart-overlay');
            if (!overlay) return;
            if (overlay.classList.contains('open')) {
                closeCart();
            } else {
                openCart();
            }
        }

        function openCart() {
            notifyUserActivity('openCart');
            const overlay = document.getElementById('servipag-cart-overlay');
            if (overlay) {
                updateCartUI();
                overlay.classList.add('open');
                _cartOpen = true;
                LOG('openCart: Carro abierto');
            }
        }

        function closeCart() {
            const overlay = document.getElementById('servipag-cart-overlay');
            if (overlay) {
                overlay.classList.remove('open');
                _cartOpen = false;
                LOG('closeCart: Carro cerrado');
            }
        }

        function agregarMasCuentas(fromVoice = false) {
            notifyUserActivity('agregarMasCuentas');
            closeCart();
            showAccountsPanel();
            if (fromVoice) {
                sayViaAvatar("De acuerdo. Puedes seleccionar otra cuenta diciendo su número, el nombre o tocándola en pantalla.");
            }
        }

        async function sayViaAvatar(text) {
            if (!text) return;
            LOG(`sayViaAvatar: "${text}"`);
            queueAvatarBubble(text);
            stopAlwaysOnListening();

            const sessionid = document.getElementById('sessionid').value;
            try {
                await fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text,
                        type: 'echo',
                        sessionid: String(sessionid)
                    })
                });
            } catch (e) {
                WARN('sayViaAvatar network error:', e);
            }
        }

        let _pendingReceiptFollowUp = false;
        let _postPaymentFollowUpSafetyTimeout = null;

        function triggerPostPaymentFollowUp() {
            if (!_conversationAwake || isSpeaking) return;
            LOG('[Post-Pago Follow-Up] Preguntando si necesita algo más tras el pago...');
            const followUpText = "¿Necesitas algo más?";
            _waitingFollowUpAck = true;

            queueAvatarBubble(followUpText);
            stopAlwaysOnListening();

            const sessionid = document.getElementById('sessionid').value;
            fetch('/human', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: followUpText,
                    type: 'echo',
                    sessionid: String(sessionid)
                })
            }).catch(e => WARN('Error al enviar post-payment follow-up:', e));
        }

        // ─── Animación de Pago en 3 Fases ──────────────────────────────────────────
        async function iniciarPago(fromVoice = false) {
            notifyUserActivity('iniciarPago');
            if (_isPaying) return;
            if (_cart.length === 0) {
                sayViaAvatar("Tu carro de pagos está vacío. Selecciona primero una cuenta de la tabla.");
                return;
            }

            _isPaying = true;
            closeCart();
            hideAccountsPanel();
            stopAlwaysOnListening();

            // Instrucción vocal del avatar
            sayViaAvatar("Por favor acerca o inserta tu tarjeta en el lector.");

            // 1 segundo de delay tras la instrucción antes de mostrar la animación del lector
            await new Promise(r => setTimeout(r, 1000));

            const overlay = document.getElementById('payment-animation-overlay');
            const phase1 = document.getElementById('pay-phase-waiting');
            const phase2 = document.getElementById('pay-phase-validating');
            const phase3 = document.getElementById('pay-phase-paid');
            const progressFill = document.getElementById('pay-progress-fill-el');

            if (overlay) overlay.classList.add('open');

            // FASE 1: Esperando medio de pago (1.6s)
            if (phase1) phase1.classList.add('active');
            if (phase2) phase2.classList.remove('active');
            if (phase3) phase3.classList.remove('active');
            if (progressFill) progressFill.style.width = '0%';

            LOG('[Pago] FASE 1: Esperando tarjeta / medio de pago...');

            await new Promise(r => setTimeout(r, 1600));

            // FASE 2: Cargando / Validando Transacción (1.9s)
            if (phase1) phase1.classList.remove('active');
            if (phase2) phase2.classList.add('active');
            if (progressFill) {
                setTimeout(() => { progressFill.style.width = '100%'; }, 50);
            }

            LOG('[Pago] FASE 2: Cargando y validando con Servipag Transbank...');

            // Guardar IDs pagados antes de limpiar el carro
            const cuentasIds = _cart.map(c => c.id_cuenta);
            let comprobanteData = null;
            try {
                const res = await fetch('/api/servipag/pagar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        rut: _currentRut,
                        cuentas_ids: cuentasIds
                    })
                });
                const resp = await res.json();
                if (resp.code === 0 && resp.data) {
                    comprobanteData = resp.data;
                }
            } catch (err) {
                WARN('Error en llamada a /api/servipag/pagar:', err);
            }

            await new Promise(r => setTimeout(r, 1900));

            // FASE 3: ¡Pagado! Su cuenta ha sido pagada exitosamente
            if (phase2) phase2.classList.remove('active');
            if (phase3) phase3.classList.add('active');

            const receiptNum = document.getElementById('pay-receipt-num');
            const receiptTotal = document.getElementById('pay-receipt-total');
            const receiptDate = document.getElementById('pay-receipt-date');

            const totalPagado = _cart.reduce((s, i) => s + (i.monto || 0), 0);
            if (receiptNum) receiptNum.textContent = comprobanteData ? comprobanteData.comprobante : `#SP-${Math.floor(100000 + Math.random() * 900000)}`;
            if (receiptTotal) receiptTotal.textContent = `$${totalPagado.toLocaleString('es-CL')}`;
            if (receiptDate) receiptDate.textContent = comprobanteData ? comprobanteData.fecha : new Date().toLocaleString('es-CL');

            LOG('[Pago] FASE 3: ¡Pagado! Su cuenta ha sido pagada exitosamente.');

            // 1. Vaciar el carrito de inmediato y deseleccionar cuentas
            _cart = [];
            updateCartUI();

            // 2. Marcar de inmediato las cuentas pagadas en la tabla como 'es_pagada = true', monto = 0, y deseleccionarlas
            if (_currentAccounts && _currentAccounts.length > 0) {
                _currentAccounts.forEach(acc => {
                    if (cuentasIds.includes(acc.id_cuenta)) {
                        acc.es_pagada = true;
                        acc.monto = 0;
                        acc.estado = 'pagada';
                        acc.monto_formateado = '$0';
                    }
                });
            }
            if (_currentClient) {
                if (_currentClient.cuentas) {
                    _currentClient.cuentas.forEach(acc => {
                        if (cuentasIds.includes(acc.id_cuenta)) {
                            acc.es_pagada = true;
                            acc.monto = 0;
                            acc.estado = 'pagada';
                            acc.monto_formateado = '$0';
                        }
                    });
                }
                renderAccountsTable(_currentClient);
            }

            // 3. Sincronizar en segundo plano con el backend sin reabrir el panel
            if (_currentRut) {
                setTimeout(() => {
                    loadAndShowAccounts(_currentRut, false);
                }, 1500);
            }

            // 4. El avatar vocaliza el comprobante y programa la pregunta de seguimiento (inactividad)
            const successSpeech = "¡Excelente! Tu pago ha sido procesado exitosamente. Se ha enviado el comprobante a tu correo.";
            _pendingReceiptFollowUp = true;
            sayViaAvatar(successSpeech);

            // Fallback de seguridad: si tras 7.5s no se detectó el fin de habla, forzar el follow-up
            clearTimeout(_postPaymentFollowUpSafetyTimeout);
            _postPaymentFollowUpSafetyTimeout = setTimeout(() => {
                if (_pendingReceiptFollowUp) {
                    _pendingReceiptFollowUp = false;
                    if (_conversationAwake && !isSpeaking) {
                        cerrarAnimacionPago();
                        triggerPostPaymentFollowUp();
                    }
                }
            }, 7500);

            // Timer visible de 5 segundos para el botón "Aceptar" tras terminar el pago
            const btnAccept = document.getElementById('pay-btn-accept');
            let countdown = 5;
            if (btnAccept) {
                btnAccept.textContent = `Aceptar (${countdown}s)`;
            }

            if (_payCountdownInterval) {
                clearInterval(_payCountdownInterval);
                _payCountdownInterval = null;
            }

            _payCountdownInterval = setInterval(() => {
                countdown--;
                if (btnAccept) {
                    btnAccept.textContent = countdown > 0 ? `Aceptar (${countdown}s)` : 'Aceptar';
                }
                if (countdown <= 0) {
                    clearInterval(_payCountdownInterval);
                    _payCountdownInterval = null;
                    cerrarAnimacionPago();
                }
            }, 1000);
        }

        function cerrarAnimacionPago() {
            if (_payCountdownInterval) {
                clearInterval(_payCountdownInterval);
                _payCountdownInterval = null;
            }
            const btnAccept = document.getElementById('pay-btn-accept');
            if (btnAccept) {
                btnAccept.textContent = 'Aceptar';
            }

            const overlay = document.getElementById('payment-animation-overlay');
            if (overlay) overlay.classList.remove('open');
            _isPaying = false;

            // Mantener la tabla de cuentas y el carro cerrados y limpios tras el pago
            hideAccountsPanel();
            closeCart();
            _cart = [];
            updateCartUI();
        }

        // Selección por comando de voz cuando la tabla está activa
        function selectAccountByVoice(voiceText) {
            if (!_currentAccounts || _currentAccounts.length === 0) return false;
            // Si el texto contiene un RUT o identificador largo, no procesarlo como selección de cuenta
            if (hasCompleteRut(voiceText) || /\b\d{6,}\b/.test(voiceText)) {
                return false;
            }

            const norm = normalizeUserInput(voiceText).toLowerCase();

            const handleAccountSelected = (acc) => {
                const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');
                if (isPaid) {
                    LOG(`[Voz] Cuenta pagada seleccionada: ${acc.empresa_nombre}`);
                    sayViaAvatar(`Tu cuenta de ${acc.empresa_nombre} ya se encuentra pagada y al día. No tiene deuda pendiente.`);
                    return true;
                }
                toggleAccountInCart(acc, true);
                return true;
            };

            // 1. Detección prioritaria por nombre de empresa (ej: "enel", "chilectra", "aguas andinas", "vtr", "cge", "costanera norte")
            for (let i = 0; i < _currentAccounts.length; i++) {
                const acc = _currentAccounts[i];
                const empName = (acc.empresa_nombre || '').toLowerCase();
                const empId = (acc.empresa_id || '').toLowerCase();
                if (norm.includes(empName) || (empId && norm.includes(empId)) || (empId === 'enel' && norm.includes('chilectra'))) {
                    LOG(`[Voz] Selección por nombre de empresa: ${acc.empresa_nombre}`);
                    return handleAccountSelected(acc);
                }
            }

            // 2. Detección prioritaria por categoría (ej: "la luz", "el agua", "el gas", "el tag", "internet")
            for (let i = 0; i < _currentAccounts.length; i++) {
                const acc = _currentAccounts[i];
                const cat = (acc.categoria || '').toLowerCase();
                if (cat && (norm.includes(cat) || (cat === 'agua' && norm.includes('aguas')) || (cat === 'luz' && (norm.includes('electricidad') || norm.includes('eléctrica'))))) {
                    LOG(`[Voz] Selección por categoría de servicio: ${cat} (${acc.empresa_nombre})`);
                    return handleAccountSelected(acc);
                }
            }

            // 3. Detección por número (ej: "la 1", "uno", "cuenta 2", "el dos", "opción 2")
            // Solo coincide con selector explícito o término numérico aislado
            const numWords = {
                '1': 1, 'uno': 1, 'primera': 1, 'primero': 1,
                '2': 2, 'dos': 2, 'segunda': 2, 'segundo': 2,
                '3': 3, 'tres': 3, 'tercera': 3, 'tercero': 3,
                '4': 4, 'cuatro': 4, 'cuarta': 4, 'cuarto': 4,
                '5': 5, 'cinco': 5, 'quinta': 5, 'quinto': 5
            };
            const matchNum = norm.match(
                /^(?:(?:la|el|opci[oó]n|cuenta|n[uú]mero)\s+)?(1|2|3|4|5|uno|dos|tres|cuatro|cinco|primera|primero|segunda|segundo|tercera|tercero|cuarta|quinta)$/i
            ) || norm.match(
                /\b(?:la\s+|el\s+|opci[oó]n\s+|cuenta\s+|n[uú]mero\s+|fila\s+|quiero\s+la\s+|quiero\s+el\s+|pagar\s+la\s+|pagar\s+el\s+)(1|2|3|4|5|uno|dos|tres|cuatro|cinco|primera|primero|segunda|segundo|tercera|tercero|cuarta|quinta)\b/i
            );

            if (matchNum) {
                const w = matchNum[1].toLowerCase();
                const targetIdx = (numWords[w] || parseInt(w, 10)) - 1;
                if (targetIdx >= 0 && targetIdx < _currentAccounts.length) {
                    const acc = _currentAccounts[targetIdx];
                    LOG(`[Voz] Selección por número: opción ${targetIdx + 1} -> ${acc.empresa_nombre}`);
                    return handleAccountSelected(acc);
                }
            }

            return false;
        }

        // Auto-seleccionar cuenta al carro cuando el avatar responde sobre una cuenta específica con deuda a pagar
        function autoSelectAccountFromAvatarResponse(avatarMsg) {
            if (!avatarMsg || !_currentAccounts || _currentAccounts.length === 0) return;
            const norm = normalizeUserInput(avatarMsg).toLowerCase();

            // Si el mensaje es el saludo general ("las cuentas disponibles se muestran en pantalla"), no auto-seleccionar ninguna
            if (norm.includes('las cuentas disponibles se muestran en pantalla')) {
                return;
            }

            for (let i = 0; i < _currentAccounts.length; i++) {
                const acc = _currentAccounts[i];
                const isPaid = Boolean(acc.es_pagada || acc.monto === 0 || acc.estado === 'pagada' || acc.estado === 'sin_deuda');
                if (isPaid) continue;

                const empName = (acc.empresa_nombre || '').toLowerCase();
                const empId = (acc.empresa_id || '').toLowerCase();
                const cat = (acc.categoria || '').toLowerCase();

                const mentionsCompany = norm.includes(empName) || (empId && norm.includes(empId)) || (empId === 'enel' && norm.includes('chilectra')) || (cat && norm.includes(cat));
                const isDebtOffer = norm.includes('deuda') || norm.includes('pagarla') || norm.includes('cobro');

                if (mentionsCompany && isDebtOffer) {
                    const alreadyInCart = _cart.some(item => item.id_cuenta === acc.id_cuenta);
                    if (!alreadyInCart) {
                        _cart.push(acc);
                        updateCartUI();
                        if (_currentClient) renderAccountsTable(_currentClient);
                        LOG(`[AutoSelect] Cuenta detectada y agregada al carro tras respuesta del avatar: ${acc.empresa_nombre}`);
                    }
                    break;
                }
            }
        }

        async function numpadSubmit() {
            if (_rutBuffer.length < 7) return;
            const finalRut = formatRutDisplay(_rutBuffer);
            LOG(`numpadSubmit: RUT ingresado desde teclado táctil: "${finalRut}"`);

            _isWaitingRut = false;
            clearTimeout(_pendingCommitTimeout);
            _pendingCommitTimeout = null;
            _voiceAccumulator = '';

            // Notificar actividad para reiniciar timers de inactividad y cancelar follow-up
            notifyUserActivity('numpadSubmit');

            // Ocultar teclado inmediatamente tras digitar
            hideRutNumpad();

            // Detener escucha activa para que el mic no capture ruido en la transición
            stopAlwaysOnListening();

            // Despertar modelo / conversación
            wakeUpModel();

            // Cargar y desplegar tabla de cuentas del cliente de inmediato
            loadAndShowAccounts(finalRut);

            // Enviar el RUT al LLM
            await sendToLLM(finalRut);
        }


        LOG('Modo ASR: SpeechRecognition');

        // ─── Estado UI ─────────────────────────────────────────────────────────────
        function setState(state, text) {
            LOG(`setState → ${state}: "${text}"`);
            document.body.className = 'state-' + state;
            document.getElementById('status-text').textContent = text;
        }

        function setUserText(text, dim = false) {
            const line = document.getElementById('user-line');
            const span = document.getElementById('user-text');
            line.style.display = text ? 'flex' : 'none';
            span.textContent = text;
            span.className = 'transcript-text' + (dim ? ' dim' : '');
        }

        // ─── Pantalla completa ─────────────────────────────────────────────────────
        function toggleFullscreen() {
            LOG('toggleFullscreen llamado');
            const el = document.documentElement;
            if (!document.fullscreenElement &&
                !document.webkitFullscreenElement &&
                !document.mozFullScreenElement) {
                const req = el.requestFullscreen
                    || el.webkitRequestFullscreen
                    || el.mozRequestFullScreen
                    || el.msRequestFullscreen;
                if (req) req.call(el).catch(e => WARN('Fullscreen error:', e));
            } else {
                const exit = document.exitFullscreen
                    || document.webkitExitFullscreen
                    || document.mozCancelFullScreen
                    || document.msExitFullscreen;
                if (exit) exit.call(document);
            }
        }

        // ─── Tap-to-start (Android autoplay fix) ──────────────────────────────────
        function handleTapToStart() {
            LOG('handleTapToStart — tap del usuario detectado');
            const overlay = document.getElementById('tap-overlay');
            if (overlay) overlay.style.display = 'none';

            const videoEl = document.getElementById('video');
            videoEl.muted = false;
            _audioUnlocked = true;
            LOG('Video desmutado dentro del gesto de usuario');

            if (videoEl.srcObject) {
                videoEl.play()
                    .then(() => LOG('video.play() OK tras tap'))
                    .catch(e => WARN('video.play() rechazado tras tap:', e.name, e.message));
            }

            connectRTC();
        }

        // ─── WebRTC ────────────────────────────────────────────────────────────────
        function connectRTC() {
            if (isConnected) { LOG('connectRTC: ya conectado, ignorando'); return; }
            LOG('connectRTC: iniciando...');
            setState('connecting', 'Conectando…');
            start();   // client.js
            document.getElementById('btn-connect').textContent = '✓ Conectado';
            document.getElementById('btn-connect').classList.add('connected');
            isConnected = true;

            const _v = document.getElementById('video');
            let _vChecks = 0;
            const _vTimer = setInterval(function () {
                _vChecks++;
                if (_v.srcObject) {
                    if (_v.paused) {
                        if (_audioUnlocked) {
                            _v.muted = false;
                            _v.play()
                                .then(function () { LOG('video.play() OK con audio'); clearInterval(_vTimer); })
                                .catch(function () {
                                    WARN('video.play() rechazó audio, fallback a muted');
                                    _v.muted = true;
                                    _audioUnlocked = false;
                                    _v.play()
                                        .then(function () { LOG('video.play() OK muted (fallback)'); clearInterval(_vTimer); })
                                        .catch(function (e) { WARN('video.play() muted fallo:', e.name); clearInterval(_vTimer); });
                                });
                        } else {
                            // Intentar reproducir directamente con audio si la política de autoplay lo permite
                            _v.muted = false;
                            _v.play()
                                .then(function () {
                                    _audioUnlocked = true;
                                    LOG('video.play() OK con audio directo (autoplay habilitado)');
                                    clearInterval(_vTimer);
                                })
                                .catch(function () {
                                    _v.muted = true;
                                    _v.play()
                                        .then(function () { LOG('video.play() OK muted (esperando interacción)'); clearInterval(_vTimer); })
                                        .catch(function (e) { WARN('video.play() muted fallo:', e.name); clearInterval(_vTimer); });
                                });
                        }
                    } else {
                        LOG('Video reproduciendo');
                        clearInterval(_vTimer);
                    }
                } else if (_vChecks > 30) {
                    WARN('15s sin stream en el video.');
                    clearInterval(_vTimer);
                }
            }, 500);
            setTimeout(() => {
                startSpeakingMonitor();
                LOG('Monitor de speaking activo — iniciando always-on listening');
                startAlwaysOnListening();
            }, 2500);
        }

        // ─── Monitor de "avatar hablando" ──────────────────────────────────────────
        // Watchdog: si el avatar lleva más de MAX_SPEAKING_MS en estado "hablando"
        // sin que el backend reporte speaking=false (latencia / corte de red), lo resetea forzosamente.
        const MAX_SPEAKING_MS = 12000;
        let _speakingWatchdog = null;

        function _clearSpeakingWatchdog() {
            clearTimeout(_speakingWatchdog);
            _speakingWatchdog = null;
        }

        function _armSpeakingWatchdog() {
            _clearSpeakingWatchdog();
            _speakingWatchdog = setTimeout(() => {
                if (isSpeaking) {
                    WARN('[Speaking Watchdog] Avatar en estado "hablando" por más de ' + (MAX_SPEAKING_MS / 1000) + 's sin fin reportado. Forzando reset.');
                    isSpeaking = false;
                    const wrap = document.getElementById('avatar-wrap');
                    if (wrap) wrap.classList.remove('avatar-speaking');
                    if (_conversationAwake) {
                        setState('listening', 'Escuchando pregunta…');
                        scheduleFollowUp();
                    } else {
                        setState('listening', 'Esperando activación…');
                    }
                    setTimeout(() => {
                        _alwaysOnActive = false;
                        isListening = false;
                        startAlwaysOnListening();
                    }, 400);
                }
            }, MAX_SPEAKING_MS);
        }

        function startSpeakingMonitor() {
            LOG('startSpeakingMonitor iniciado');
            speakCheckInterval = setInterval(async () => {
                if (!isConnected) return;
                try {
                    const sessionid = document.getElementById('sessionid').value;
                    const res = await fetch('/is_speaking', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ sessionid })
                    });
                    const data = await res.json();
                    const speaking = Boolean(data.data);
                    if (speaking !== isSpeaking) {
                        isSpeaking = speaking;
                        LOG('isSpeaking cambió →', speaking);
                        const wrap = document.getElementById('avatar-wrap');
                        if (speaking) {
                            if (wrap) wrap.classList.add('avatar-speaking');
                            setState('speaking', 'Hablando…');
                            _armSpeakingWatchdog();
                            // Cancelar CUALQUIER timer de follow-up / despedida mientras el avatar habla
                            cancelFollowUpTimers(true);
                            // Pausar reconocimiento mientras el avatar habla para no captar su propia voz ni eco
                            stopAlwaysOnListening();
                            if (_pendingAvatarBubbleText) {
                                clearTimeout(_pendingAvatarBubbleTimeout);
                                addChatBubble('avatar', _pendingAvatarBubbleText);
                                _pendingAvatarBubbleText = null;
                            }
                        } else {
                            if (wrap) wrap.classList.remove('avatar-speaking');
                            _clearSpeakingWatchdog();
                            LOG('Avatar terminó de hablar → reiniciando escucha (awake: ' + _conversationAwake + ')');
                            
                            // Si el avatar terminó de hablar y solicitó el RUT o reportó un error con el RUT, mostrar el teclado numérico táctil
                            if (_pendingRutNumpadShow) {
                                _pendingRutNumpadShow = false;
                                setTimeout(() => {
                                    showRutNumpad(!_isRutError);
                                }, 350);
                            }

                            // Si acababa de confirmar el comprobante de pago, esperar 1s y preguntar si necesita algo más
                            if (_pendingReceiptFollowUp) {
                                _pendingReceiptFollowUp = false;
                                clearTimeout(_postPaymentFollowUpSafetyTimeout);
                                _postPaymentFollowUpSafetyTimeout = null;
                                LOG('[Post-Pago] Avatar terminó de confirmar comprobante. Esperando 1s para preguntar si necesita algo más...');
                                setTimeout(() => {
                                    if (_conversationAwake && !isSpeaking) {
                                        cerrarAnimacionPago();
                                        triggerPostPaymentFollowUp();
                                    }
                                }, 1000);
                                return;
                            }

                            if (_conversationAwake) {
                                setState('listening', 'Escuchando pregunta…');
                                scheduleFollowUp();
                                if (_waitingFollowUpAck) {
                                    scheduleFollowUpAckTimeout();
                                }
                            } else {
                                setState('listening', 'Esperando activación…');
                            }

                            setTimeout(() => {
                                if (!isSpeaking && !_pendingRutNumpadShow) {
                                    _alwaysOnActive = false;
                                    isListening = false;
                                    startAlwaysOnListening();
                                }
                            }, 600);
                        }
                    }
                } catch (e) {
                    WARN('[Speaking Monitor] Error al consultar is_speaking:', e.message || e);
                }
            }, 700);
        }

        // ─── Solicitud de Permiso de Micrófono ────────────────────────────────────
        async function requestMicPermission() {
            LOG('requestMicPermission: verificando micrófono...');
            if (_preferredDeviceId) LOG(`Usando dispositivo seleccionado: ${_preferredDeviceId.slice(0, 16)}…`);
            try {
                const audioConstraints = _preferredDeviceId
                    ? { deviceId: { exact: _preferredDeviceId }, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
                    : { echoCancellation: true, noiseSuppression: true, autoGainControl: true };

                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: audioConstraints,
                    video: false
                });

                const tracks = stream.getAudioTracks();
                tracks.forEach((t, i) => {
                    LOG(`  Track[${i}]: label="${t.label}" readyState=${t.readyState}`);
                    t.stop(); // Liberar track para no bloquear SpeechRecognition
                });

                if (_conversationAwake) {
                    setState('listening', `Escuchando pregunta…`);
                } else {
                    setState('listening', `Esperando activación…`);
                }
                await dbgLoadDevices();

                LOG('Permiso de micrófono OK — Hardware libre para SpeechRecognition');
                return true;
            } catch (e) {
                ERR('requestMicPermission falló:', e.name, e.message);
                if (e.name === 'NotAllowedError') {
                    setState('ready', '⚠ Permiso de micrófono denegado');
                } else if (e.name === 'NotFoundError') {
                    setState('ready', '⚠ No se encontró micrófono');
                } else {
                    setState('ready', '⚠ Error de micrófono: ' + e.name);
                }
                return false;
            }
        }

        // ─── Speech Recognition ────────────────────────────────────────────────────
        let _recStartMs = 0;
        let _gotAnyResult = false;
        let _audioCaptureErrors = 0;
        let _networkSpeechErrors = 0;
        let _pendingCommitTimeout = null;
        let _voiceAccumulator = '';
        let _questionDispatched = false;

        const _dispatchQuestion = (rawText) => {
            if (_questionDispatched) return;
            _questionDispatched = true;
            clearTimeout(_pendingCommitTimeout);
            _pendingCommitTimeout = null;
            _voiceAccumulator = '';
            notifyUserActivity('_dispatchQuestion');

            const normalizedText = normalizeUserInput(rawText);
            if (isWakeOnlyGreeting(normalizedText)) {
                clearTimeout(_wakeBufferTimeout);
                _alwaysOnActive = false;
                wakeUpModel();
                sendGreetingAsAvatar(normalizedText);
                return;
            }

            let question = _extractQuestion(normalizedText);
            if (!question) {
                question = normalizedText.trim();
            }

            LOG(`Texto procesado para enviar: "${question}" | awake: ${_conversationAwake}`);

            if (question) {
                clearTimeout(_wakeBufferTimeout);

                if (hasCompleteRut(question)) {
                    _isWaitingRut = false;
                    // Cargar y mostrar cuentas del RUT dictado
                    const rutMatch = question.match(/(?:(?:[1-9]\d?\.?\d{3}\.?\d{3}|[1-9]\d{6,7})[-–—][0-9kK]|\b\d{7,8}[0-9kK]\b)/i);
                    if (rutMatch) {
                        loadAndShowAccounts(rutMatch[0]);
                    }
                }

                // ── Control por voz interactivo de Cuentas, Carro y Pago ──
                const normQ = question.toLowerCase();
                const isAccountsOrCartActive = _servipagPanelOpen || _cartOpen || (_currentAccounts && _currentAccounts.length > 0);

                if (isAccountsOrCartActive) {
                    // Mostrar / ver carro
                    if (/(?:mostrar|ver|abrir|ensename|enséñame)?\s*(?:el\s+)?(?:carro|carrito)/i.test(normQ) && !hasCompleteRut(question)) {
                        openCart();
                        sayViaAvatar("Aquí tienes tu carro de cuentas. ¿Deseas pagarlas ahora o agregar más?");
                        return;
                    }

                    // Cerrar carro
                    if (/(?:cerrar|ocultar)\s*(?:el\s+)?(?:carro|carrito)/i.test(normQ)) {
                        closeCart();
                        return;
                    }

                    // Mostrar / ver cuentas
                    if (/(?:mostrar|ver|abrir|ensename|enséñame)?\s*(?:las\s+)?cuentas/i.test(normQ) && !hasCompleteRut(question) && _currentClient) {
                        showAccountsPanel();
                        renderAccountsTable(_currentClient);
                        sayViaAvatar("Aquí tienes tus cuentas disponibles.");
                        return;
                    }

                    // Cerrar cuentas
                    if (/(?:cerrar|ocultar)\s*(?:las\s+)?cuentas/i.test(normQ)) {
                        hideAccountsPanel();
                        return;
                    }

                    // Agregar más cuentas
                    if (/^(?:agregar\s+m[aá]s|otra\s+cuenta|agregar\s+otra|sumar\s+otra)$/i.test(normQ)) {
                        agregarMasCuentas(true);
                        return;
                    }

                    // Selección por número (1, 2, 3...), empresa o categoría de la tabla (evaluada antes de pago genérico)
                    if (!hasCompleteRut(question) && selectAccountByVoice(question)) {
                        return;
                    }

                    // Pagar cuentas / carro / confirmación afirmativa (ej: "si quiero pagar", "si quiero", "pagar", "si por favor")
                    const cleanNorm = normQ
                        .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                        .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g, " ")
                        .replace(/\s+/g, " ")
                        .trim();

                    const isPayIntent = /^(?:si|claro|por\s+favor|porfa|dale|ok|bueno|proceder)?\s*(?:quiero\s+pagar(?:la)?|pagar(?:la)?(?:\s+ahora)?|pagemosla|paguemos|pagar\s+el\s+carro|pagar\s+las?\s+cuentas?|proceder(?:\s+con\s+el\s+pago)?|procede|cancelo)$/i.test(cleanNorm)
                        || /^(?:si|si\s+quiero|claro|claro\s+que\s+si|por\s+favor|porfa|dale|bueno|ok|proceder|si\s+por\s+favor|si\s+dale|si\s+claro|si\s+porfa|acepto|si\s+acepto)$/i.test(cleanNorm)
                        || /\b(?:quiero\s+pagar|pagar\s+ahora|pagar\s+la\s+cuenta|pagar\s+el\s+carro)\b/i.test(cleanNorm);
                    if (isPayIntent) {
                        if (_cart.length > 0) {
                            iniciarPago(true);
                            return;
                        }

                        // Si el carro no tenía items pero hay cuentas cargadas
                        if (_currentAccounts && _currentAccounts.length > 0) {
                            if (_lastAvatarMessage) {
                                autoSelectAccountFromAvatarResponse(_lastAvatarMessage);
                            }
                            if (_cart.length === 0) {
                                const debtAccounts = _currentAccounts.filter(a => (a.monto || 0) > 0 && !a.es_pagada && a.estado !== 'pagada' && a.estado !== 'sin_deuda');
                                if (debtAccounts.length === 0) {
                                    sayViaAvatar("Todas tus cuentas se encuentran pagadas y al día. No tienes cuentas pendientes de pago.");
                                    return;
                                } else if (debtAccounts.length === 1) {
                                    _cart.push(debtAccounts[0]);
                                    updateCartUI();
                                    if (_currentClient) renderAccountsTable(_currentClient);
                                } else if (debtAccounts.length > 1) {
                                    sayViaAvatar("Tienes varias cuentas con deuda disponibles. Por favor indícame cuál deseas pagar: di el número, el nombre o tócala en la pantalla.");
                                    return;
                                }
                            }
                            if (_cart.length > 0) {
                                iniciarPago(true);
                                return;
                            }
                        }
                    }
                }

                if (_isSleepWord(question)) {
                    LOG(`Palabra de despedida detectada: "${question}" → durmiendo modelo`);
                    stopAlwaysOnListening();
                    sendToLLM(question, true);
                    sleepModel(false);
                    return;
                }

                LOG(`Enviando al LLM: "${question}"`);
                _alwaysOnActive = false;
                stopAlwaysOnListening();
                sendToLLM(question);
            }
        };

        function setupRecognition() {
            LOG('setupRecognition: creando instancia...');
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRec) {
                ERR('SpeechRecognition NO disponible en este navegador');
                return null;
            }

            const rec = new SpeechRec();
            rec.lang = 'es-CL';
            rec.interimResults = true;
            rec.continuous = false;
            rec.maxAlternatives = 1;

            rec.onstart = () => {
                _recStartMs = Date.now();
                _gotAnyResult = false;
                // NOTA: Si hay un timer de pausa de dictado en curso, NO borrar el acumulador
                // para permitir concatenar el siguiente tramo de números/palabras.
                if (!_pendingCommitTimeout) {
                    _voiceAccumulator = '';
                }
                _questionDispatched = false;
                LOG(`SpeechRecognition.onstart — ESCUCHANDO (awake: ${_conversationAwake}, acumulado="${_voiceAccumulator}")`);
                isListening = true;
                setState('listening', _conversationAwake ? 'Escuchando pregunta…' : 'Esperando activación…');
                setUserText(_voiceAccumulator ? normalizeUserInput(_voiceAccumulator) : '', false);
            };

            rec.onresult = (event) => {
                if (isSpeaking) {
                    LOG('SpeechRecognition ignorado: avatar hablando');
                    return;
                }
                _gotAnyResult = true;
                let interim = '';
                let final = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const t = event.results[i][0].transcript;
                    const conf = event.results[i][0].confidence;
                    if (event.results[i].isFinal) {
                        LOG(`Resultado FINAL: "${t}" (confidence=${conf.toFixed(2)})`);
                        final += t;
                    } else {
                        interim += t;
                    }
                }
                if (interim) LOG(`Resultado interim: "${interim}"`);

                const rawText = (final || interim).trim();
                if (!rawText) return;

                notifyUserActivity('voz detectada');

                if (!_conversationAwake) {
                    if (_containsWakeWord(rawText)) {
                        wakeUpModel();
                        LOG(`Wake-word detectada en: "${rawText}" → Modelo despierto`);
                        setState('listening', 'Escuchando pregunta…');
                        clearTimeout(_wakeBufferTimeout);
                        _wakeBufferTimeout = setTimeout(() => {
                            if (_conversationAwake && !_extractQuestion(rawText)) {
                                LOG('Buffer expirado sin pregunta → saludo directo del avatar');
                                sendGreetingAsAvatar();
                            }
                        }, BUFFER_MS);
                    } else {
                        setUserText(final || interim, true);
                        return;
                    }
                } else {
                    resetInactivityTimer();
                    clearTimeout(_followUpTimeoutId);
                    clearTimeout(_followUpAckTimeoutId);
                    _waitingFollowUpAck = false;
                }

                // ── RESULTADOS INTERMEDIOS (INTERIM): el usuario sigue hablando ──
                if (!final) {
                    const display = _voiceAccumulator ? (_voiceAccumulator + ' ' + rawText) : rawText;
                    setUserText(normalizeUserInput(display), true);
                    return;
                }

                // ── RESULTADO FINAL DE VOZ ──
                clearTimeout(_pendingCommitTimeout);
                _pendingCommitTimeout = null;

                // 1. Saludo aislado ("Hola", "Buenas"): enviar de inmediato sin demora ni LLM
                if (isWakeOnlyGreeting(rawText)) {
                    LOG(`[Wake Saludo Inmediato] Saludo detectado ("${rawText}") → enviando echo directo`);
                    _voiceAccumulator = '';
                    setUserText(normalizeUserInput(rawText), false);
                    try { rec.stop(); } catch (e) {}
                    _dispatchQuestion(rawText);
                    return;
                }

                // 2. RUT completo en la frase actual: enviar de inmediato
                if (hasCompleteRut(rawText)) {
                    LOG(`[RUT Completo Directo] RUT válido detectado en frase: "${rawText}" → enviando de inmediato`);
                    _voiceAccumulator = '';
                    setUserText(normalizeUserInput(rawText), false);
                    try { rec.stop(); } catch (e) {}
                    _dispatchQuestion(rawText);
                    return;
                }

                // 3. Dictado por pausas de RUT o números:
                // Solo se activa si:
                // - NO hay cuentas activas ni carro en pantalla (evita confundir opciones de cuentas con RUT)
                // - Se está esperando el RUT (_isWaitingRut) o el usuario dijo "rut" / "mi rut es"
                // - La frase contiene ÚNICAMENTE números/dígitos (isPureNumberOrRutDictation)
                const isAccountsActive = _servipagPanelOpen || _cartOpen || (_currentAccounts && _currentAccounts.length > 0);
                const isPureNumber = isPureNumberOrRutDictation(rawText);
                const isRutContext = _isWaitingRut || /\brut\b/i.test(rawText);

                if (!isAccountsActive && isRutContext && isPureNumber) {
                    const combined = _voiceAccumulator ? (_voiceAccumulator + ' ' + rawText) : rawText;
                    if (hasCompleteRut(combined)) {
                        LOG(`[RUT Dictation Acumulado] RUT completo alcanzado ("${combined}") → enviando de inmediato`);
                        _voiceAccumulator = '';
                        setUserText(normalizeUserInput(combined), false);
                        try { rec.stop(); } catch (e) {}
                        _dispatchQuestion(combined);
                        return;
                    }

                    // Aún incompleto: guardar fragmento y esperar 1500ms de pausa
                    _voiceAccumulator = combined;
                    setUserText(normalizeUserInput(_voiceAccumulator), false);
                    LOG(`[RUT Dictation Fragmento] Acumulado: "${_voiceAccumulator}" → esperando 1500ms para siguiente tramo...`);
                    _pendingCommitTimeout = setTimeout(() => {
                        if (_conversationAwake && _voiceAccumulator && !_questionDispatched) {
                            LOG(`[RUT Commit tras 1.5s de silencio] Enviando acumulado: "${_voiceAccumulator}"`);
                            const txt = _voiceAccumulator;
                            _voiceAccumulator = '';
                            _pendingCommitTimeout = null;
                            try { rec.stop(); } catch (e) {}
                            _dispatchQuestion(txt);
                        }
                    }, 1500);
                    return;
                }

                // 4. Cualquier otra interacción normal (preguntas, "quiero pagar el agua", "si quiero", selección de cuentas, etc.)
                // ¡Despachar DE INMEDIATO y asegurar buffer completamente limpio!
                _voiceAccumulator = '';
                setUserText(normalizeUserInput(rawText), false);
                LOG(`[Conversación Inmediata] Despachando frase final: "${rawText}"`);
                try { rec.stop(); } catch (e) {}
                _dispatchQuestion(rawText);
            };

            rec.onerror = (e) => {
                const elapsed = Date.now() - _recStartMs;
                if (e.error === 'aborted' || e.error === 'no-speech') {
                    // Eventos normales: 'aborted' ocurre al detener la escucha (esperado),
                    // 'no-speech' es timeout normal de silencio.
                    LOG(`SpeechRecognition.onerror — evento "${e.error}" (normal, omitido) elapsed=${elapsed}ms`);
                    return;
                }
                ERR(`SpeechRecognition.onerror — error="${e.error}" elapsed=${elapsed}ms`);

                if (e.error === 'audio-capture') {
                    _audioCaptureErrors++;
                    ERR(`audio-capture #${_audioCaptureErrors}: mic no accesible`);
                    setState('ready', '⚠ Error captura de audio — intenta de nuevo');
                } else if (e.error === 'not-allowed') {
                    ERR('not-allowed: permiso de micrófono denegado');
                    setState('ready', '⚠ Permiso de micrófono denegado');
                } else if (e.error === 'network') {
                    _networkSpeechErrors++;
                    ERR('network error #' + _networkSpeechErrors + ': SpeechRecognition no puede conectar a los servidores de voz.');
                    setState('ready', 'Error de red STT — reintenta o verifica soporte de voz');
                } else {
                    setState('ready', `⚠ Error: ${e.error}`);
                }
                stopListening();
            };


            rec.onend = () => {
                const elapsed = Date.now() - _recStartMs;
                LOG(`SpeechRecognition.onend — elapsed=${elapsed}ms, gotResult=${_gotAnyResult}, pendingTimeout=${!!_pendingCommitTimeout}, acumulado="${_voiceAccumulator}"`);

                // Si hay un timeout de commit pendiente de dictado de RUT (fragmento incompleto esperando pausa):
                // Reiniciar escucha para capturar el siguiente tramo antes de que expire el temporizador de 1.5s
                if (_pendingCommitTimeout && _voiceAccumulator) {
                    LOG(`[onend] Fragmento de RUT esperando más dígitos ("${_voiceAccumulator}"). Reiniciando escucha.`);
                    stopListening();
                    if (_alwaysOnActive) {
                        setTimeout(() => {
                            if (_alwaysOnActive && !isListening && !isSpeaking) {
                                startAlwaysOnListening();
                            }
                        }, 100);
                    }
                    return;
                }

                // Si por alguna razón el recognizer terminó y quedó texto acumulado sin timeout ni despacho:
                if (_conversationAwake && _voiceAccumulator && !_questionDispatched) {
                    clearTimeout(_pendingCommitTimeout);
                    _pendingCommitTimeout = null;
                    LOG(`[onend Auto-Commit] Enviando buffer remanente: "${_voiceAccumulator}"`);
                    const txt = _voiceAccumulator;
                    _voiceAccumulator = '';
                    _dispatchQuestion(txt);
                    stopListening();
                    return;
                }

                _voiceAccumulator = '';
                clearTimeout(_pendingCommitTimeout);
                _pendingCommitTimeout = null;

                if (!_gotAnyResult && elapsed < 1500) {
                    WARN(`Fin rápido sin resultado (${elapsed}ms) → reintentando en 600ms`);
                    stopListening();
                    setTimeout(() => {
                        if (!isListening && _alwaysOnActive) {
                            recognition = setupRecognition();
                            if (recognition) {
                                try { recognition.start(); }
                                catch (ex) { ERR('reintento falló:', ex.name); }
                            }
                        }
                    }, 600);
                    return;
                }

                stopListening();

                if (_alwaysOnActive) {
                    LOG('SpeechRecognition onend: always-on activo → reiniciando en 500ms');
                    setTimeout(() => {
                        if (_alwaysOnActive && !isListening && !isSpeaking) {
                            startAlwaysOnListening();
                        }
                    }, 500);
                }
            };

            return rec;
        }

        let _stopTimeout = null;
        function forceStopRecognition() {
            if (!recognition) { stopListening(); return; }
            LOG('forceStopRecognition: llamando stop()...');
            recognition.stop();

            clearTimeout(_stopTimeout);
            _stopTimeout = setTimeout(() => {
                if (isListening) {
                    WARN('forceStopRecognition: onend no disparó en 2.5s → abort() forzado');
                    try { recognition.abort(); } catch (e) { LOG('abort() excepción (ignorada):', e.name); }
                    stopListening();
                }
            }, 2500);
        }

        function stopListening() {
            LOG('stopListening');
            isListening = false;
            clearTimeout(_stopTimeout);

            if (!isSpeaking && !_alwaysOnActive && _conversationAwake) {
                setState('thinking', 'Pensando…');
            }
        }

        // ─── Escucha siempre activa con wake-word ────────────────────────────────
        function startAlwaysOnListening() {
            if (!isConnected) {
                LOG('startAlwaysOnListening: avatar no conectado, ignorando');
                return;
            }
            if (isSpeaking) {
                LOG('startAlwaysOnListening: avatar hablando, esperando a que termine');
                return;
            }
            if (isListening) {
                LOG('startAlwaysOnListening: ya escuchando, ignorando');
                return;
            }

            _alwaysOnActive = true;
            LOG(`startAlwaysOnListening: iniciando escucha continua (awake: ${_conversationAwake})`);

            if (_conversationAwake) {
                setState('listening', 'Escuchando pregunta…');
                resetInactivityTimer();
            } else {
                setState('listening', 'Esperando activación…');
            }

            requestMicPermission().then(ok => {
                if (!ok) {
                    LOG('startAlwaysOnListening: sin permiso de micrófono');
                    _alwaysOnActive = false;
                    setState('ready', '⚠ Sin permiso de micrófono');
                    return;
                }

                if (!_audioUnlocked) {
                    const videoEl = document.getElementById('video');
                    videoEl.muted = false;
                    _audioUnlocked = true;
                    if (videoEl.srcObject) {
                        videoEl.play().catch(e => WARN('play() audio unlock error:', e.name));
                    }
                    LOG('🔊 Audio del avatar desbloqueado al obtener permiso de micrófono');
                }

                LOG('startAlwaysOnListening: modo SpeechRecognition (always-on)');
                _audioCaptureErrors = 0;
                _networkSpeechErrors = 0;
                recognition = setupRecognition();
                if (recognition) {
                    try {
                        recognition.start();
                        LOG('recognition.start() llamado (always-on)');
                    } catch (e) {
                        ERR('recognition.start() excepción (always-on):', e.name, e.message);
                        _alwaysOnActive = false;
                        stopListening();
                    }
                } else {
                    WARN('SpeechRecognition no disponible en este navegador');
                    _alwaysOnActive = false;
                    setState('ready', '⚠ SpeechRecognition no disponible');
                }
            });
        }

        function stopAlwaysOnListening() {
            LOG('stopAlwaysOnListening: deteniendo escucha continua');
            _alwaysOnActive = false;
            clearTimeout(_wakeBufferTimeout);
            clearTimeout(_pendingCommitTimeout);
            _pendingCommitTimeout = null;
            _voiceAccumulator = '';
            if (recognition) {
                try { recognition.abort(); } catch (e) { LOG('abort() excepción (ignorada):', e.name); }
            }
            stopListening();
        }

        // ─── Saludo del avatar al detectar wake-word sin pregunta ────────────────
        async function sendGreetingAsAvatar(userGreetingText = '') {
            const greetingText = _randomGreeting();
            LOG(`sendGreetingAsAvatar: "${greetingText}" (user: "${userGreetingText}")`);
            setState('thinking', 'Pensando…');
            if (userGreetingText) {
                setUserText(userGreetingText, false);
                addChatBubble('user', userGreetingText);
            }
            queueAvatarBubble(greetingText);
            stopAlwaysOnListening();

            const sessionid = document.getElementById('sessionid').value;
            try {
                await fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: greetingText,
                        type: 'echo',
                        interrupt: true,
                        sessionid: String(sessionid)
                    })
                });
            } catch (err) {
                ERR('sendGreetingAsAvatar: error de red:', err);
                setTimeout(() => {
                    if (!isSpeaking && _conversationAwake && !isListening) {
                        setState('listening', 'Escuchando pregunta…');
                        _alwaysOnActive = false;
                        startAlwaysOnListening();
                    }
                }, 1500);
            }
        }

        // ─── Enviar al LLM / backend (con streaming y burbujas) ─────────────────
        async function sendToLLM(text, isSleepWord = false) {
            if (!text) return;
            notifyUserActivity('sendToLLM');
            LOG(`sendToLLM: "${text}" (isSleepWord=${isSleepWord})`);
            setState('thinking', 'Pensando…');
            setUserText(text, false);
            addChatBubble('user', text);

            const sessionid = document.getElementById('sessionid').value;

            if (isSleepWord) {
                const clean = text.toLowerCase().trim().replace(/[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]/g,"");
                let farewellText = "De acuerdo. Si necesitas algo más, aquí estaré.";
                if (clean.includes('gracias') || clean.includes('chao') || clean.includes('adios') || clean.includes('luego')) {
                    farewellText = "De nada. ¡Que tengas un excelente día!";
                }

                queueAvatarBubble(farewellText);
                clearServerHistory();

                try {
                    await fetch('/human', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: farewellText,
                            type: 'echo',
                            sessionid: String(sessionid)
                        })
                    });
                } catch (err) {
                    ERR('sendToLLM farewell error:', err);
                } finally {
                    addChatBubble('system', 'Conversación finalizada. Di "Hola" para activar de nuevo.');
                }
                return;
            }

            try {
                const res = await fetch('/human', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text,
                        type: 'chat',
                        interrupt: true,
                        stream: true,
                        sessionid: String(sessionid)
                    })
                });
                LOG('sendToLLM: respuesta status', res.status);
                
                if (!res.body) {
                    throw new Error("Respuesta del servidor no soporta streaming.");
                }

                const reader = res.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let fullText = '';
                let avatarBubble = null;

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const chunk = decoder.decode(value, { stream: true });
                    fullText += chunk;

                    if (!avatarBubble && fullText.trim()) {
                        avatarBubble = addChatBubble('avatar', '');
                    }

                    if (avatarBubble) {
                        avatarBubble.textContent = normalizarTexto(fullText);
                        const container = document.getElementById('chat-container');
                        if (container) {
                            container.scrollTop = container.scrollHeight;
                        }
                    }
                }
                if (avatarBubble) {
                    avatarBubble.textContent = normalizarTexto(fullText);
                }

                LOG('sendToLLM: stream de respuesta del LLM completado:', fullText);
                _lastAvatarMessage = fullText;
                autoSelectAccountFromAvatarResponse(fullText);

                // Si la respuesta del avatar instruye pagar o acercar tarjeta al lector, y hay cuentas en el carro/cargadas, iniciar la animación de pago
                const isRedirectToPayment = /(?:plataforma\s+de\s+pago|tarjeta\s+en\s+el\s+lector|acerca.*tarjeta|inserta.*tarjeta|acerque.*tarjeta|inserte.*tarjeta)/i.test(fullText);
                if (isRedirectToPayment && !_isPaying) {
                    if (_cart.length === 0 && _currentAccounts && _currentAccounts.length > 0) {
                        const debtAccounts = _currentAccounts.filter(a => (a.monto || 0) > 0 && !a.es_pagada && a.estado !== 'pagada' && a.estado !== 'sin_deuda');
                        if (debtAccounts.length === 1) {
                            _cart.push(debtAccounts[0]);
                            updateCartUI();
                            if (_currentClient) renderAccountsTable(_currentClient);
                        }
                    }
                    if (_cart.length > 0) {
                        LOG('[sendToLLM] Avatar confirmó transición a pago → iniciando animación de pago');
                        iniciarPago(false);
                    }
                }

                // Una vez que el LLM termina de generar, el TTS ya procesa en el backend.
                // Aseguramos que la escucha permanezca detenida para no captar la voz del avatar.
                // El speaking monitor activará 'Hablando…' en cuanto el audio empiece a salir.
                if (fullText.trim()) {
                    setState('thinking', 'Pensando…');
                    stopAlwaysOnListening();
                }

                // Detectar si el avatar está pidiendo el RUT o reportando error / número incompleto / no existencia
                const isAskingRut = /(?:rut|cliente|identificador).*(?:ind[ií]ca|dime|ingresa|digita|cu[aá]l|proporciona|favor|dame|asociad)|(?:cu[aá]l|qu[eé]|dime|ingresa|digita).*(?:rut|cliente|identificador)|(?:incompleto|completo)/i.test(fullText);
                const isRutError = /(?:no\s+(?:encontr[eé]|figura|est[aá]\s+registrado|existe|pude\s+encontrar)|no\s+tengo\s+registrado|no\s+se\s+registran|verifica|revisa|error|inv[aá]lido|no\s+coincide|incompleto).*(?:rut|cuenta|cliente|n[uú]mero)|(?:rut|cuenta|cliente|n[uú]mero).*(?:no\s+(?:encontr[eé]|figura|est[aá]\s+registrado|existe|se\s+registran)|incorrecto|inv[aá]lido|incompleto)/i.test(fullText);

                if (isAskingRut || isRutError) {
                    LOG(`sendToLLM: Avatar solicita o reporta error en RUT (asking=${isAskingRut}, error=${isRutError}). Programando apertura de teclado táctil.`);
                    _pendingRutNumpadShow = true;
                    _isRutError = isRutError;
                    _isWaitingRut = true;
                } else {
                    _isWaitingRut = false;
                }

                // Fallback de seguridad: si tras 3.5s del stream el avatar no reportó habla, reactivar escucha y mostrar teclado si correspondía
                setTimeout(() => {
                    if (!isSpeaking && _conversationAwake && !isListening) {
                        LOG('Fallback post-stream: avatar no reportó habla, reactivando escucha...');
                        setState('listening', 'Escuchando pregunta…');
                        _alwaysOnActive = false;
                        startAlwaysOnListening();
                        if (_pendingRutNumpadShow) {
                            _pendingRutNumpadShow = false;
                            showRutNumpad(!_isRutError);
                        }
                    }
                }, 3500);

            } catch (err) {
                ERR('sendToLLM: error de red o streaming:', err);
                setState('ready', 'Error de red — intenta de nuevo');
                setTimeout(() => {
                    if (_conversationAwake && !isListening) {
                        _alwaysOnActive = false;
                        startAlwaysOnListening();
                    }
                }, 2000);
            }
        }

        // ─── Interrumpir avatar ────────────────────────────────────────────────────
        async function interruptAvatar() {
            LOG('interruptAvatar');
            const sessionid = document.getElementById('sessionid').value;
            try {
                await fetch('/interrupt_talk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sessionid: String(sessionid) })
                });
                LOG('interruptAvatar: solicitud enviada');
            } catch (e) { WARN('interruptAvatar: error de red', e); }

            setTimeout(() => {
                LOG('interruptAvatar: reiniciando always-on listening tras interrupción');
                isSpeaking = false;
                startAlwaysOnListening();
            }, 300);
        }



        // ─── Auto-conectar al cargar ───────────────────────────────────────────────
        window.addEventListener('DOMContentLoaded', () => {
            const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
            const isFirefox = /Firefox\//.test(navigator.userAgent);

            LOG('DOMContentLoaded - isMobile:', isMobile, '| isFirefox:', isFirefox);
            LOG('Secure context:', window.isSecureContext, '| protocol:', location.protocol);

            if (!window.isSecureContext) {
                WARN('CONTEXTO NO SEGURO (HTTP). SpeechRecognition NO funcionara. Usar HTTPS.');
            }

            if (isFirefox) {
                WARN('Firefox detectado: SpeechRecognition NO disponible en Firefox.');
                WARN('Para usar el micrófono usa Chrome, Chromium o Edge.');
            }

            if (isMobile) {
                LOG('Mobile detectado - overlay visible, esperando tap');
            } else {
                LOG('Desktop detectado - auto-conectando.');
                const overlay = document.getElementById('tap-overlay');
                if (overlay) overlay.style.display = 'none';
                setTimeout(connectRTC, 800);
            }

            // Desbloqueo global de audio con cualquier interacción del usuario (click, tecla o touch)
            const _globalUnlockAudio = () => {
                const videoEl = document.getElementById('video');
                if (videoEl && videoEl.muted) {
                    videoEl.muted = false;
                    _audioUnlocked = true;
                    if (videoEl.paused && videoEl.srcObject) {
                        videoEl.play().catch(e => WARN('video.play() en unlock global:', e.name));
                    }
                    LOG('Audio del avatar desbloqueado por interacción del usuario');
                }
            };
            document.addEventListener('click', _globalUnlockAudio);
            document.addEventListener('keydown', _globalUnlockAudio);
            document.addEventListener('touchstart', _globalUnlockAudio);

            // Soporte robusto de teclado físico y pegado (Ctrl+V) para RUT
            document.addEventListener('keydown', (e) => {
                // No interceptar si el usuario está interactuando con otro input
                if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') && e.target.id !== 'numpad-display') {
                    return;
                }

                const overlay = document.getElementById('rut-numpad-overlay');
                const isOpen = overlay && overlay.classList.contains('open');

                if (/^[0-9]$/.test(e.key)) {
                    e.preventDefault();
                    if (!isOpen) showRutNumpad(false);
                    numpadPress(e.key);
                } else if (e.key === 'k' || e.key === 'K') {
                    e.preventDefault();
                    if (!isOpen) showRutNumpad(false);
                    numpadPress('K');
                } else if (isOpen && e.key === 'Backspace') {
                    e.preventDefault();
                    numpadBackspace();
                } else if (isOpen && e.key === 'Escape') {
                    e.preventDefault();
                    hideRutNumpad();
                } else if (isOpen && e.key === 'Enter') {
                    e.preventDefault();
                    numpadSubmit();
                }
            });

            // Soporte para pegar (Ctrl+V) un RUT directamente en la pantalla
            document.addEventListener('paste', (e) => {
                const pasted = (e.clipboardData || window.clipboardData)?.getData('text');
                if (!pasted) return;
                const clean = pasted.replace(/[^0-9kK]/g, '').toUpperCase();
                if (clean.length >= 7 && clean.length <= 9) {
                    e.preventDefault();
                    showRutNumpad(true);
                    _rutBuffer = clean;
                    updateNumpadDisplay();
                    LOG('RUT pegado exitosamente desde portapapeles:', _rutBuffer);
                    loadAndShowAccounts(_rutBuffer);
                }
            });
        });
    