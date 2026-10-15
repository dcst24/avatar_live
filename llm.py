###############################################################################
#  LLM integration — Ollama (Qwen)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

import os
import re
import time
import json
import threading
import unicodedata
import requests
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger


def normalizar(text: str) -> str:
    """
    Limpia y normaliza el texto tanto para el TTS como para el chat de texto:
    - Remueve formato Markdown (asteriscos **, *, almohadillas #, backticks `, etc.)
    - Remueve flechas (→, ->, =>, etc.)
    - Remueve viñetas y guiones de lista (•, -, —, –, etc.)
    - Remueve corchetes, llaves, barras y caracteres especiales (| / \\ [ ] { } ~ ^)
    - Convierte el símbolo '%' a la palabra 'por ciento'
    - Convierte precios con '$' a formato pronunciable (ej: '$599.990' -> '599.990 pesos')
    - Elimina emojis y caracteres no pronunciables
    - Colapsa espacios redundantes
    """
    if not text:
        return ""

    # 1. Reemplazar porcentajes por texto pronunciable
    text = re.sub(r'(\d+)\s*%', r'\1 por ciento', text)

    # 2. Convertir precios con signo $ a pesos (ej: $599.990 -> 599.990 pesos)
    text = re.sub(r'\$(\d[\d\.]*)(?:\s*pesos)?', r'\1 pesos', text)
    text = re.sub(r'(\b\d[\d\.]*\s*pesos)([a-zA-ZáéíóúÁÉÍÓÚñÑ])', r'\1 \2', text)

    # 3. Reemplazar flechas de cualquier tipo por un espacio
    text = re.sub(r'[→⇒➜➞➝➔]|->|=>|<-|<=|↔', ' ', text)

    # 4. Eliminar markdown de negrita, cursiva, tachado y encabezados
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`+([^`]+)`+', r'\1', text)
    text = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.MULTILINE)

    # 5. Eliminar viñetas, bullets y guiones en cualquier posición
    text = re.sub(r'[-—–]+', ' ', text)
    text = re.sub(r'[*#|_\\/\[\]{}~^<>•·●○■◆▪\(\)]', ' ', text)

    # 6. Eliminar emojis (rangos unicode de emoticones y símbolos visuales)
    text = re.sub(
        r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]',
        '',
        text
    )

    # 7. Limpiar signos de puntuación duplicados o mal espaciados
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    text = re.sub(r'[,]{2,}', ',', text)
    text = re.sub(r'[.]{2,}', '.', text)
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()


# Alias para compatibilidad
normalizar_texto_para_tts = normalizar

# ─── Historial de conversación (memoria por sesión) ──────────────────────────
# Clave: sessionid (str)  →  Valor: lista de mensajes [{role, content}, ...]
_histories: dict = {}
MAX_HISTORY_TURNS = 10  # máximo de turnos (user+assistant) a conservar en memoria
OLLAMA_URL   = "http://200.29.189.27:65535/api/chat"
OLLAMA_MODEL = "qwen3-vl:32b-instruct"
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "4096"))

# ─── Control cooperativo de cancelación de streaming por sesión ──────────────
_cancelled_sessions: set = set()
_cancelled_sessions_lock = threading.Lock()

def abort_generation(sessionid: str):
    """Marca la sesión para abortar inmediatamente el streaming del LLM."""
    if not sessionid:
        return
    with _cancelled_sessions_lock:
        _cancelled_sessions.add(sessionid)
    logger.info(f"[LLM] Generación abortada para sesión: {sessionid}")

def _is_cancelled(sessionid: str) -> bool:
    if not sessionid:
        return False
    with _cancelled_sessions_lock:
        return sessionid in _cancelled_sessions

def _clear_cancellation(sessionid: str):
    if not sessionid:
        return
    with _cancelled_sessions_lock:
        _cancelled_sessions.discard(sessionid)

# ─── Base de Conocimiento y Prompt: Mutual de Seguridad ───────────────────────
_active_products: dict = {}  # sessionid -> prod dict (compatibilidad)

def find_matching_product(text: str = None):
    return None

def reload_catalog() -> None:
    pass

BASE_SYSTEM_PROMPT = '''Eres el asistente virtual oficial de Mutual de Seguridad.
Tu función es orientar e informar a los trabajadores y usuarios de manera clara, precisa, amable y directa basándote ÚNICAMENTE en la información oficial provista a continuación.

INFORMACIÓN OFICIAL Y BASE DE CONOCIMIENTO:

Accidente de trabajo:
Es toda lesión que ocurre a causa o con ocasión del trabajo y que provoca incapacidad o muerte. Si sufres un accidente, informa a tu jefatura o empleador lo antes posible. Si no puedes hacerlo, acude directamente a Mutual de Seguridad. El empleador debe presentar la denuncia DIAT dentro de las 24 horas desde que toma conocimiento del accidente. Para consultar el estado del trabajador, llama al 600 2000 555, opción 3. Recuerda que la información médica es confidencial.

Accidente de trayecto:
Es el accidente que ocurre en el trayecto directo entre el hogar y el trabajo, de ida o regreso, o entre dos lugares de trabajo. Si sufres uno, informa a tu jefatura o empleador lo antes posible. Si no puedes hacerlo, acude directamente a Mutual de Seguridad. El empleador debe presentar la denuncia DIAT dentro de las 24 horas desde que toma conocimiento del accidente. Para consultar el estado del trabajador, llama al 600 2000 555, opción 3. Recuerda que la información médica es confidencial.

REGLAS ESTRICTAS DE RESPUESTA:
- Responde siempre en español de Chile natural, claro, profesional y directo.
- Tu respuesta es leída mediante síntesis de voz (TTS). NUNCA uses asteriscos (*), negritas (**), guiones (- ni —), viñetas (•), flechas (→) ni caracteres especiales.
- No uses rodeos ni introducciones innecesarias.
- Saludo inicial: Si el usuario te saluda, salúdalo cordialmente, indícale que eres el asistente virtual de Mutual de Seguridad y pregúntale si tiene dudas sobre accidentes de trabajo o de trayecto.
- Si preguntan qué es un accidente de trabajo o cómo proceder ante uno, responde basándote fielmente en la definición e instrucciones de Accidente de trabajo.
- Si preguntan qué es un accidente de trayecto o cómo proceder ante uno, responde basándote fielmente en la definición e instrucciones de Accidente de trayecto.
- Si preguntan por el plazo para presentar la denuncia DIAT, indica que el empleador debe presentar la denuncia DIAT dentro de las 24 horas desde que toma conocimiento del accidente.
- Si preguntan por el estado del trabajador o teléfono de atención, indica que deben llamar al 600 2000 555, opción 3, y recuerda que la información médica es confidencial.
- LÍMITE DE CONOCIMIENTO (MUY IMPORTANTE): Este avatar SOLO debe limitarse a responder información de Mutual de Seguridad sobre accidentes de trabajo y de trayecto. Si el usuario realiza una pregunta sobre cualquier tema ajeno a esta información (por ejemplo celulares, compras, ofertas, retail u otros temas generales), niégate amablemente respondiendo: "Disculpa, como asistente de Mutual de Seguridad solo puedo orientarte sobre accidentes de trabajo y de trayecto. Para otras consultas puedes llamar al 600 2000 555."
'''

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

def _get_dynamic_system_prompt(user_msg: str = "", history: list = [], sessionid: str = "", datainfo: dict = None) -> str:
    """Retorna el prompt de sistema oficial de Mutual de Seguridad."""
    return BASE_SYSTEM_PROMPT


# ─── Detección inteligente de oraciones para streaming de voz ultra-rápido ───
MIN_CHUNK_LEN = 40  # caracteres mínimos antes de enviar un fragmento al avatar TTS (40 chars ≈ 5-7 palabras, permite latencia mínima)

def _is_sentence_boundary(chunk_buf: str) -> bool:
    """
    Determina si el buffer actual ha alcanzado un límite de oración natural para enviar al avatar.
    Soporta '.', '?', '!' y signos orientales, pero evita cortar en medio de precios
    chilenos como '599.990' o '1.069.990'.
    """
    if len(chunk_buf) < MIN_CHUNK_LEN:
        return False

    trimmed = chunk_buf.rstrip()
    if not trimmed:
        return False

    last_char = trimmed[-1]

    # Signos inequívocos de fin de frase
    if last_char in ('?', '!', ';', ':', '\n', '？', '！', '；', '：'):
        return True

    # Punto: verificar que no sea separador de miles en un número/precio (ej: '599.')
    if last_char in ('.', '。'):
        if re.search(r'\d\.$', trimmed):
            return False
        return True

    # Si el buffer es largo (> 80 chars) y termina en coma, también cortar para fluidez
    if len(trimmed) > 80 and last_char == ',':
        return True

    return False


# ─── Warmup en segundo plano de Ollama para respuestas instantáneas ─────────
def _warmup_ollama():
    """Ejecuta una consulta liviana a Ollama en segundo plano al arrancar el servidor."""
    try:
        logger.info("[LLM] Iniciando warmup en segundo plano para precargar modelo Ollama en GPU...")
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": "OK"},
                {"role": "user", "content": "1"}
            ],
            "options": {"num_ctx": OLLAMA_NUM_CTX},
            "stream": False,
            "keep_alive": "7200m"
        }
        res = requests.post(OLLAMA_URL, json=payload, timeout=25)
        if res.status_code == 200:
            logger.info("[LLM] Warmup de Ollama completado exitosamente. Modelo listo en VRAM.")
        else:
            logger.warning(f"[LLM] Warmup Ollama retorno status: {res.status_code}")
    except Exception as e:
        logger.warning(f"[LLM] Warmup de Ollama omitido: {e}")

threading.Thread(target=_warmup_ollama, daemon=True).start()


def clear_conversation(sessionid: str) -> None:
    """Elimina el historial de conversación y producto activo de la sesión indicada."""
    if sessionid in _histories:
        del _histories[sessionid]
        logger.info(f"[LLM] Historial borrado para sesión: {sessionid}")
    else:
        logger.info(f"[LLM] clear_conversation: no había historial para {sessionid}")
    if sessionid in _active_products:
        del _active_products[sessionid]


def _get_messages_with_history(sessionid: str, user_message: str, datainfo: dict = None) -> list:
    """Construye la lista completa de mensajes para el LLM incluyendo el historial."""
    if datainfo is None:
        datainfo = {}
    history = _histories.get(sessionid, [])
    dynamic_prompt = _get_dynamic_system_prompt(user_message, history, sessionid=sessionid, datainfo=datainfo)
    messages = [{"role": "system", "content": dynamic_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def _append_to_history(sessionid: str, user_message: str, assistant_reply: str) -> None:
    """Agrega el turno actual al historial y recorta si supera MAX_HISTORY_TURNS."""
    if not sessionid:
        return
    history = _histories.setdefault(sessionid, [])
    history.append({"role": "user",      "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
    # Recortar: conservar sólo los últimos MAX_HISTORY_TURNS turnos (2 mensajes por turno)
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        _histories[sessionid] = history[-max_msgs:]
        logger.debug(f"[LLM] Historial recortado a {MAX_HISTORY_TURNS} turnos para sesión {sessionid}")

append_to_history = _append_to_history


def llm_response(message: str, avatar_session: "BaseAvatar", datainfo: dict = {}):
    """
    Envía `message` al LLM y alimenta al avatar con los fragmentos de respuesta
    a medida que van llegando (chunking por puntuación).
    Mantiene historial de conversación por sesión.
    """
    sessionid: str = datainfo.get("sessionid", "")
    try:
        start = time.perf_counter()
        logger.info(f"[LLM] Enviando mensaje (sesión={sessionid}): {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": _get_messages_with_history(sessionid, message, datainfo),
            "options": {
                "num_ctx": OLLAMA_NUM_CTX,
                # Sin límite num_predict: el modelo qwen3-vl usa tokens internos de
                # razonamiento que consumen el presupuesto; 70 truncaba la respuesta visible.
                "temperature": 0.4,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
            },
            "stream": False,
            "keep_alive": "7200m",
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()

        elapsed = time.perf_counter() - start
        data = response.json()

        # La API de Ollama devuelve: { "message": { "role": "assistant", "content": "..." } }
        full_text: str = data["message"]["content"]
        logger.info(f"[LLM] Respuesta en {elapsed:.2f}s: {full_text[:120]}...")

        # Texto completamente normalizado para el chat e historial
        clean_text = normalizar(full_text)
        _append_to_history(sessionid, message, clean_text)

        # Enviar respuesta completa al avatar en un solo bloque para máxima fluidez y perfecta sincronización
        if clean_text:
            logger.info(f"[LLM] -> avatar: {clean_text}")
            avatar_session.put_msg_txt(clean_text, datainfo)

        return clean_text

    except requests.exceptions.Timeout:
        logger.error("[LLM] Timeout al conectar con Ollama (>120s)")
        return "Disculpa, el servidor de lenguaje tardó demasiado en responder."
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[LLM] No se pudo conectar a Ollama: {e}")
        return "Disculpa, no me pude conectar al servidor de lenguaje."
    except KeyError as e:
        logger.error(f"[LLM] Respuesta inesperada de Ollama, clave faltante: {e}")
        return "Disculpa, recibí una respuesta inesperada."
    except Exception as e:
        logger.exception("[LLM] Error inesperado:")
        return f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"


def llm_response_stream(message: str, avatar_session: "BaseAvatar", datainfo: dict = {}):
    """
    Envía `message` al LLM y rinde los fragmentos de respuesta a medida que van llegando
    de Ollama, alimentando al avatar en tiempo real y haciendo yield para el streaming HTTP.
    Mantiene historial de conversación por sesión.
    """
    sessionid: str = datainfo.get("sessionid", "")
    _clear_cancellation(sessionid)
    try:
        start = time.perf_counter()
        logger.info(f"[LLM Stream] Enviando mensaje (sesión={sessionid}): {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": _get_messages_with_history(sessionid, message, datainfo),
            "options": {
                "num_ctx": OLLAMA_NUM_CTX,
                # Sin límite num_predict: el modelo qwen3-vl usa tokens internos de
                # razonamiento que consumen el presupuesto; 70 truncaba la respuesta visible.
                "temperature": 0.4,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
            },
            "stream": True,
            "keep_alive": "7200m",
        }

        response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=120)
        response.raise_for_status()

        full_text = ""

        for line in response.iter_lines():
            if _is_cancelled(sessionid):
                logger.info(f"[LLM Stream] Cancelación detectada en iteración para sesión: {sessionid}")
                break
            if not line:
                continue

            try:
                data = json.loads(line.decode('utf-8'))
                content = data.get("message", {}).get("content", "")
                if not content:
                    continue

                full_text += content

                # Rinde el token de inmediato para la interfaz de chat en tiempo real
                yield content

                if _is_cancelled(sessionid):
                    break

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        # Enviar respuesta normalizada completa al avatar en un solo bloque fluido si no fue cancelado
        if not _is_cancelled(sessionid) and full_text.strip():
            clean_text = normalizar(full_text.strip())
            if clean_text:
                logger.info(f"[LLM Stream] -> avatar (completo fluido): {clean_text}")
                avatar_session.put_msg_txt(clean_text, datainfo)
            # Guardar turno completo en historial (normalizado)
            _append_to_history(sessionid, message, clean_text)

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s (cancelado={_is_cancelled(sessionid)}), total chars={len(full_text)}")

    except Exception as e:
        if not _is_cancelled(sessionid):
            logger.exception("[LLM Stream] Error:")
            yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"