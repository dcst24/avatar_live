###############################################################################
#  WebSocket ASR Handler — aiohttp
#
#  Endpoint: GET /ws/asr?sessionid=<id>
#
#  Protocolo cliente → servidor:
#    - Binary frames: PCM 16-bit LE, 16kHz, mono (chunks de 960 samples = 60ms)
#    - JSON: {"type": "config", "sessionid": "...", "lang": "es"}
#    - JSON: {"type": "stop"}   → fuerza transcripción final del buffer
#
#  Protocolo servidor → cliente (JSON):
#    {"type": "transcript", "text": "...", "is_final": true/false}
#    {"type": "llm_chunk",  "text": "..."}
#    {"type": "llm_done",   "full_text": "..."}
#    {"type": "state",      "state": "listening|processing|speaking|sleeping"}
#    {"type": "error",      "msg": "..."}
###############################################################################

import json
import asyncio
import time
from aiohttp import web, WSMsgType
from utils.logger import logger
from server.session_manager import session_manager


# ─── Wake-word y sleep-word (espejo de las constantes del frontend) ───────────
WAKE_WORDS = ['hola', 'oye', 'disculpa', 'permiso', 'necesito ayuda', 'asistente', 'buenas']

SLEEP_WORDS = [
    'no', 'gracias', 'chao', 'adios', 'nada mas', 'ninguna', 'ninguno',
    'hasta luego', 'eso es todo', 'no gracias'
]

WAKE_ONLY_GREETINGS = [
    '¡Hola! ¿En qué te puedo ayudar?',
    '¡Buenas! ¿Buscas algo en especial?',
    '¡Hola! ¿Necesitas ayuda para encontrar algo?',
    'Aquí estoy, ¿en qué te ayudo?',
]

INACTIVITY_TIMEOUT_S = 120   # 2 minutos
FOLLOWUP_TIMEOUT_S   = 30    # 30 s de silencio → preguntar si necesita algo más
WAKE_BUFFER_S        = 5     # espera tras wake-word sin pregunta

import random
def _random_greeting():
    return random.choice(WAKE_ONLY_GREETINGS)


def _contains_wake_word(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in WAKE_WORDS)


def _extract_question(text: str) -> str:
    """Elimina la wake-word del inicio del texto y retorna la pregunta restante."""
    lower = text.lower()
    best_idx, best_word = -1, ''
    for w in WAKE_WORDS:
        i = lower.find(w)
        if i != -1 and (best_idx == -1 or i < best_idx):
            best_idx, best_word = i, w
    if best_idx == -1:
        return text.strip()
    after = text[best_idx + len(best_word):]
    # Quitar comas, puntos, signos de inicio
    import re
    after = re.sub(r'^[,.\s¿¡]+', '', after)
    return after.strip()


def _is_sleep_word(text: str) -> bool:
    clean = text.lower().strip()
    import re
    clean = re.sub(r'[.,\/#!$%\^&\*;:{}=\-_`~()¿?¡!]', '', clean)
    return any(clean == w or clean.startswith(w + ' ') for w in SLEEP_WORDS)


# ─── Handler principal ────────────────────────────────────────────────────────

async def handle(request: web.Request) -> web.WebSocketResponse:
    """
    Handler WebSocket para transcripción ASR en tiempo real.
    Accedido como GET /ws/asr?sessionid=<id>
    """
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    sessionid = request.rel_url.query.get('sessionid', '0')
    logger.info(f"[WS-ASR] Nueva conexión. sessionid={sessionid}")

    # Obtener recursos compartidos del app
    asr_instance   = request.app.get('whisper_asr')
    llm_stream_fn  = request.app.get('llm_response_stream')
    clear_conv_fn  = request.app.get('clear_conversation')

    # ── Carga lazy del modelo si falló en startup ─────────────────────────────
    if asr_instance is None:
        # Si ya falló antes de forma permanente, no reintentar
        if request.app.get('whisper_asr_failed'):
            failed_reason = request.app.get('whisper_asr_failed_reason', 'Error desconocido')
            await ws.send_json({"type": "error",
                                "msg": f"ASR no disponible: {failed_reason}"})
            await ws.close()
            return ws

        logger.info("[WS-ASR] whisper_asr no disponible en app, intentando carga lazy...")
        try:
            from asr.whisper_asr import WhisperASR
            asr_cfg = request.app.get('asr_config', {})
            asr_instance = WhisperASR(
                model_size=asr_cfg.get('model_size', 'small'),
                language=asr_cfg.get('language', 'es'),
                device=asr_cfg.get('device', 'auto'),
            )
            # Notificar al cliente que está cargando
            await ws.send_json({"type": "state", "state": "loading",
                                "text": "Cargando modelo ASR, espera..."})
            # Cargar modelo en thread aparte para no bloquear el event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, asr_instance.load_model)
            request.app['whisper_asr'] = asr_instance
            logger.info("[WS-ASR] Carga lazy del modelo exitosa.")
        except Exception as e:
            # Marcar fallo permanente para no reintentar en cada conexión
            request.app['whisper_asr_failed'] = True
            request.app['whisper_asr_failed_reason'] = str(e)
            logger.error(f"[WS-ASR] Carga lazy del modelo falló (permanente): {e}")
            await ws.send_json({"type": "error",
                                "msg": f"No se pudo cargar el modelo Whisper: {e}"})
            await ws.close()
            return ws


    # ── Máquina de estados ASR ────────────────────────────────────────────────
    # LISTENING   : escuchando, procesando audio y transcripciones
    # PROCESSING  : LLM ejecutándose, descartar audio y transcripciones
    # SPEAKING    : avatar hablando, descartar audio y transcripciones
    ASR_LISTENING  = 'listening'
    ASR_PROCESSING = 'processing'
    ASR_SPEAKING   = 'speaking'

    _asr_state = ASR_LISTENING   # estado actual

    # ── Estado de conversación ───────────────────────────────────────────────
    conversation_awake   = False
    wake_detected        = False
    last_wake_text       = ''
    waiting_followup_ack = False

    inactivity_task  = None
    followup_task    = None
    wake_buffer_task = None
    followup_ack_task = None
    speaking_monitor_task = None

    # ── Helpers de envío ─────────────────────────────────────────────────────

    async def send(obj: dict):
        if not ws.closed:
            try:
                await ws.send_json(obj)
            except Exception:
                pass

    async def send_state(state: str, text: str = ''):
        await send({"type": "state", "state": state, "text": text})

    def set_asr_state(new_state: str):
        nonlocal _asr_state
        if _asr_state != new_state:
            logger.info(f"[WS-ASR] Estado: {_asr_state} → {new_state}")
            _asr_state = new_state
            # Limpiar buffer de audio al entrar en modos no-escucha
            if new_state in (ASR_PROCESSING, ASR_SPEAKING):
                asr_instance.reset()

    # ── Lógica de sleep / wake ────────────────────────────────────────────────

    def cancel_task(t):
        if t is not None and not t.done():
            t.cancel()

    async def clear_history():
        if clear_conv_fn:
            clear_conv_fn(sessionid)
            logger.info(f"[WS-ASR] Historial borrado para sesión {sessionid}")

    async def sleep_model(show_bubble: bool = False):
        nonlocal conversation_awake, wake_detected, waiting_followup_ack
        nonlocal inactivity_task, followup_task, followup_ack_task, wake_buffer_task
        logger.info("[WS-ASR] Durmiendo modelo.")
        conversation_awake   = False
        wake_detected        = False
        waiting_followup_ack = False
        cancel_task(inactivity_task)
        cancel_task(followup_task)
        cancel_task(followup_ack_task)
        cancel_task(wake_buffer_task)
        await clear_history()
        await send_state('sleeping', 'Esperando activación…')
        if show_bubble:
            await send({"type": "system_msg",
                        "text": 'Conversación finalizada. Di "Hola" para activar de nuevo.'})

    def wake_up_model():
        nonlocal conversation_awake
        if not conversation_awake:
            logger.info("[WS-ASR] Despertando modelo.")
            conversation_awake = True
        reset_inactivity_timer()

    def reset_inactivity_timer():
        nonlocal inactivity_task
        cancel_task(inactivity_task)
        if not conversation_awake:
            return
        loop = asyncio.get_event_loop()
        inactivity_task = loop.create_task(_inactivity_timeout())

    async def _inactivity_timeout():
        try:
            await asyncio.sleep(INACTIVITY_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        nonlocal conversation_awake, wake_detected
        logger.info("[WS-ASR] Inactividad: volviendo a modo espera.")
        conversation_awake = False
        wake_detected      = False
        await clear_history()
        await send_state('listening', 'Esperando activación…')
        await send({"type": "session_cleared"})

    def schedule_followup():
        nonlocal followup_task, followup_ack_task, waiting_followup_ack
        cancel_task(followup_task)
        cancel_task(followup_ack_task)
        waiting_followup_ack = False
        if not conversation_awake:
            return
        loop = asyncio.get_event_loop()
        followup_task = loop.create_task(_followup_timeout())

    async def _followup_timeout():
        try:
            await asyncio.sleep(FOLLOWUP_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        nonlocal waiting_followup_ack
        logger.info("[WS-ASR] 30s de silencio → enviando follow-up al avatar.")
        waiting_followup_ack = True
        followup_text = "¿Necesitas algo más?"

        avatar_session = session_manager.get_session(sessionid)
        if avatar_session:
            avatar_session.put_msg_txt(followup_text, {"sessionid": sessionid})

        await send({"type": "llm_done", "full_text": followup_text, "is_followup": True})

        # Iniciar timer de 30s para despedida automática si no responde
        loop = asyncio.get_event_loop()
        nonlocal followup_ack_task
        followup_ack_task = loop.create_task(_followup_ack_timeout())

    async def _followup_ack_timeout():
        try:
            await asyncio.sleep(FOLLOWUP_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        nonlocal waiting_followup_ack
        if not waiting_followup_ack:
            return
        logger.info("[WS-ASR] Sin respuesta al follow-up → despedida automática.")
        waiting_followup_ack = False
        farewell = "Muy bien, si necesitas algo más no dudes en llamarme. ¡Que tengas un excelente día!"
        avatar_session = session_manager.get_session(sessionid)
        if avatar_session:
            avatar_session.put_msg_txt(farewell, {"sessionid": sessionid})
        await send({"type": "llm_done", "full_text": farewell, "is_farewell": True})
        await sleep_model(show_bubble=False)

    # ── Envío al LLM (streaming) ──────────────────────────────────────────────

    async def send_to_llm(text: str, is_sleep: bool = False):
        nonlocal conversation_awake
        logger.info(f"[WS-ASR] Enviando al LLM: \"{text}\" (sleep={is_sleep})")
        set_asr_state(ASR_PROCESSING)
        await send_state(ASR_PROCESSING, 'Procesando…')

        avatar_session = session_manager.get_session(sessionid)
        if avatar_session is None:
            await send({"type": "error", "msg": "Sesión de avatar no encontrada"})
            set_asr_state(ASR_LISTENING)
            return

        if is_sleep:
            clean = text.lower().strip()
            farewell = "De nada. ¡Que tengas un excelente día!" \
                       if any(w in clean for w in ['gracias', 'chao', 'adios', 'luego']) \
                       else "De acuerdo. Si necesitas algo más, aquí estaré."

            avatar_session.put_msg_txt(farewell, {"sessionid": sessionid})
            await send({"type": "llm_done", "full_text": farewell})
            await clear_history()
            await send({"type": "system_msg",
                        "text": 'Conversación finalizada. Di "Hola" para activar de nuevo.'})
            # Lanzar monitor de fin de habla (despedida)
            loop = asyncio.get_event_loop()
            loop.create_task(_wait_speaking_end())
            return

        if llm_stream_fn is None:
            await send({"type": "error", "msg": "LLM no disponible"})
            set_asr_state(ASR_LISTENING)
            return

        # Interrumpir el avatar si está hablando
        if avatar_session.is_speaking():
            avatar_session.flush_talk()

        full_text = ''
        try:
            loop = asyncio.get_event_loop()
            q: asyncio.Queue = asyncio.Queue()

            def run_llm():
                """Ejecuta el generador síncrono en un thread y pone cada chunk en la queue."""
                try:
                    datainfo = {"sessionid": sessionid}
                    for chunk in llm_stream_fn(text, avatar_session, datainfo):
                        loop.call_soon_threadsafe(q.put_nowait, chunk)
                except Exception as e:
                    loop.call_soon_threadsafe(q.put_nowait, Exception(str(e)))
                finally:
                    loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel de fin

            # Lanzar el thread sin esperar (ejecuta en paralelo)
            import threading
            t = threading.Thread(target=run_llm, daemon=True)
            t.start()

            # Consumir chunks desde la queue de forma asíncrona
            while True:
                item = await q.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    await send({"type": "error", "msg": str(item)})
                    break
                full_text += item
                await send({"type": "llm_chunk", "text": item})

        except Exception as e:
            logger.error(f"[WS-ASR] Error en send_to_llm: {e}")
            await send({"type": "error", "msg": str(e)})
            set_asr_state(ASR_LISTENING)
            await send_state(ASR_LISTENING, 'Escuchando…')
            return

        await send({"type": "llm_done", "full_text": full_text})
        logger.info(f"[WS-ASR] LLM completado. chars={len(full_text)}")

        # Esperar a que el avatar empiece y termine de hablar
        loop = asyncio.get_event_loop()
        loop.create_task(_wait_speaking_end())

    # ── Procesamiento de transcripción ────────────────────────────────────────

    async def on_transcript(text: str, is_final: bool):
        """
        Llamado por el ASR cuando hay un resultado.
        SOLO procesa si estamos en estado LISTENING.
        """
        nonlocal conversation_awake, wake_detected, last_wake_text
        nonlocal waiting_followup_ack, followup_task, followup_ack_task, wake_buffer_task

        if not text:
            return

        # ── GUARDIA: ignorar transcripciones si no estamos escuchando ──────────
        if _asr_state != ASR_LISTENING:
            logger.debug(f"[WS-ASR] Transcript ignorado (estado={_asr_state}): \"{text[:40]}\"")
            return

        logger.info(f"[WS-ASR] Transcript (final={is_final}): \"{text}\"")
        await send({"type": "transcript", "text": text, "is_final": is_final})

        if not is_final:
            return

        # Cancelar timers de follow-up cuando hay actividad del usuario
        cancel_task(followup_task)
        cancel_task(followup_ack_task)
        waiting_followup_ack = False

        # ── MODO CONVERSACIÓN ABIERTA ────────────────────────────────────────
        if conversation_awake:
            reset_inactivity_timer()
            is_sleep = _is_sleep_word(text)
            if is_sleep:
                logger.info(f"[WS-ASR] Despedida detectada: \"{text}\"")
                await sleep_model(False)
            await send_to_llm(text, is_sleep)
            return

        # ── MODO ESPERA DE WAKE-WORD ─────────────────────────────────────────
        if not wake_detected:
            if _contains_wake_word(text):
                wake_detected    = True
                last_wake_text   = text
                logger.info(f"[WS-ASR] Wake-word detectada en: \"{text}\"")
                await send_state('listening', 'Escuchando pregunta…')

                # Buffer: si no llega pregunta en WAKE_BUFFER_S → enviar saludo
                cancel_task(wake_buffer_task)
                loop = asyncio.get_event_loop()
                wake_buffer_task = loop.create_task(_wake_buffer_timeout())
            else:
                # Sin wake-word: ignorar
                logger.debug(f"[WS-ASR] Sin wake-word en: \"{text}\"")
                return

        # ── Wake-word detectada: procesar texto ──────────────────────────────
        if wake_detected:
            question = _extract_question(text)
            logger.info(f"[WS-ASR] Pregunta extraída: \"{question}\"")

            if question:
                cancel_task(wake_buffer_task)
                wake_detected = False
                wake_up_model()
                await send_to_llm(question)
            # else: solo wake-word, el buffer ya está corriendo

    async def _wake_buffer_timeout():
        nonlocal wake_detected, last_wake_text
        try:
            await asyncio.sleep(WAKE_BUFFER_S)
        except asyncio.CancelledError:
            return
        if wake_detected:
            logger.info(f"[WS-ASR] Buffer expirado → enviando wake-word sola: \"{last_wake_text}\"")
            wake_detected = False
            wake_up_model()
            set_asr_state(ASR_PROCESSING)
            await send_state(ASR_PROCESSING, 'Procesando…')
            await send_to_llm(last_wake_text)

    # ── Monitor de fin de habla del avatar ──────────────────────────────────

    async def _wait_speaking_end():
        """
        Espera a que el avatar empiece a hablar y luego a que termine.
        Cuando termina, vuelve al estado LISTENING.
        """
        nonlocal speaking_monitor_task
        set_asr_state(ASR_SPEAKING)

        avatar_session = session_manager.get_session(sessionid)
        if avatar_session is None:
            # Sin sesión de avatar, volver directo a listening
            set_asr_state(ASR_LISTENING)
            await send_state(ASR_LISTENING, 'Escuchando…')
            return

        # Esperar a que el avatar empiece a hablar (máx 3s)
        start_wait = time.time()
        while not avatar_session.is_speaking() and (time.time() - start_wait) < 3.0:
            await asyncio.sleep(0.1)

        if not avatar_session.is_speaking():
            # No empezó a hablar, volver a listening
            logger.debug("[WS-ASR] Avatar no empezó a hablar, volviendo a listening")
            set_asr_state(ASR_LISTENING)
            await send_state(ASR_LISTENING, 'Escuchando…')
            return

        logger.info("[WS-ASR] Avatar empezó a hablar, esperando que termine...")
        await send_state(ASR_SPEAKING, 'Hablando…')

        # Esperar a que termine de hablar
        while avatar_session.is_speaking():
            await asyncio.sleep(0.2)

        logger.info("[WS-ASR] Avatar terminó de hablar, volviendo a LISTENING")
        set_asr_state(ASR_LISTENING)
        asr_instance.reset()  # limpiar cualquier audio acumulado mientras hablaba
        await send_state(ASR_LISTENING, 'Escuchando…')
        # Notificar al cliente que puede escuchar de nuevo
        await send({"type": "speaking_done"})

        if conversation_awake:
            schedule_followup()

    # ── Configurar callback del ASR ───────────────────────────────────────────
    loop = asyncio.get_event_loop()

    def _asr_callback(text: str, is_final: bool):
        """Callback del thread de ASR — programa la coroutine en el event loop."""
        asyncio.run_coroutine_threadsafe(on_transcript(text, is_final), loop)

    # ── Iniciar sesión ASR ────────────────────────────────────────────────────
    asr_instance.on_transcript = _asr_callback
    asr_instance.start()
    await send_state(ASR_LISTENING, 'Esperando activación…')
    logger.info(f"[WS-ASR] Sesión iniciada. Esperando audio...")

    # ── Loop principal de mensajes WebSocket ──────────────────────────────────
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                # Chunk de audio PCM — pasar al ASR
                asr_instance.feed(msg.data)

            elif msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get('type', '')

                    if msg_type == 'config':
                        # Reconfigurar sessionid si se envía en el mensaje
                        sid = data.get('sessionid', sessionid)
                        logger.info(f"[WS-ASR] Config recibida: sessionid={sid}")

                    elif msg_type == 'stop':
                        # Forzar transcripción del buffer actual
                        logger.info("[WS-ASR] Stop recibido — forzando transcripción final")
                        asr_instance.stop()

                    elif msg_type == 'reset':
                        # Resetear buffer sin transcribir (p.ej. avatar empezó a hablar)
                        asr_instance.reset()

                    elif msg_type == 'ping':
                        await send({"type": "pong"})

                except json.JSONDecodeError:
                    pass

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break

    except Exception as e:
        logger.error(f"[WS-ASR] Error en loop de mensajes: {e}")

    finally:
        cancel_task(inactivity_task)
        cancel_task(followup_task)
        cancel_task(followup_ack_task)
        cancel_task(wake_buffer_task)
        if speaking_monitor_task and not speaking_monitor_task.done():
            speaking_monitor_task.cancel()
        asr_instance.reset()
        logger.info(f"[WS-ASR] Conexión cerrada. sessionid={sessionid}")

    return ws
