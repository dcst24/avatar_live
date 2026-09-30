###############################################################################
#  LLM integration — Ollama (FitLife Gym & Payment Assistant)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

import os
import re
import time
import json
import threading
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
    - Convierte precios con '$' a formato pronunciable (ej: '$34.990' -> '34.990 pesos')
    - Elimina emojis y caracteres no pronunciables
    - Colapsa espacios redundantes
    """
    if not text:
        return ""

    # 1. Reemplazar porcentajes por texto pronunciable
    text = re.sub(r'(\d+)\s*%', r'\1 por ciento', text)

    # 2. Convertir precios con signo $ a pesos (ej: $34.990 -> 34.990 pesos)
    text = re.sub(r'\$(\d[\d\.]*)\s*(?:pesos)?', r'\1 pesos ', text)

    # 2b. Reemplazo fonético de abreviaturas comunes y RUT
    text = re.sub(r'\bctas?\b', 'cuotas', text, flags=re.IGNORECASE)
    text = re.sub(r'\bdcto\b', 'descuento', text, flags=re.IGNORECASE)
    text = re.sub(r'\bpos\b', 'terminal de pago', text, flags=re.IGNORECASE)

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

# ─── Carga dinámica de datos del Gimnasio ────────────────────────────────────
_GYM_DATA_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "gym_data.json")
_GYM_DATA: dict = {}
_PLANES_BY_ID: dict = {}
_CLIENTES_BY_RUT: dict = {}

def reload_gym_data() -> None:
    global _GYM_DATA, _PLANES_BY_ID, _CLIENTES_BY_RUT
    try:
        if os.path.exists(_GYM_DATA_PATH):
            with open(_GYM_DATA_PATH, encoding="utf-8") as f:
                _GYM_DATA = json.load(f)
        else:
            alt_path = os.path.join(os.path.dirname(__file__), "data", "gym_data.json")
            with open(alt_path, encoding="utf-8") as f:
                _GYM_DATA = json.load(f)

        _PLANES_BY_ID = {p["id"]: p for p in _GYM_DATA.get("planes", [])}
        _CLIENTES_BY_RUT = {}
        for c in _GYM_DATA.get("clientes_demo", []):
            _CLIENTES_BY_RUT[c.get("rut_limpio", "").lower()] = c
            _CLIENTES_BY_RUT[c.get("rut", "").lower()] = c
        logger.info(f"[LLM] Datos de FitLife Gym cargados ({len(_PLANES_BY_ID)} planes, {len(_CLIENTES_BY_RUT)} clientes demo)")
    except Exception as e:
        _GYM_DATA = {}
        _PLANES_BY_ID = {}
        _CLIENTES_BY_RUT = {}
        logger.error(f"[LLM] No se pudo cargar gym_data.json: {e}")

reload_gym_data()


BASE_SYSTEM_PROMPT = '''Eres el asesor comercial y asistente virtual de pagos de FitLife Club & Gym.
Tu función es brindar atención al cliente, presentar los planes de gimnasio (1, 3, 6 y 12 meses), asociar la cuenta mediante RUT y guiar el proceso de pago simulado.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS PARA VOZ):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones, menos de 25 palabras en total).
- El usuario te escucha hablar a través de un avatar en tiempo real. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones largas.
- NUNCA uses asteriscos (*), negritas (**), guiones (- o —), viñetas (•) ni caracteres especiales.
- Di los precios en pesos sin el signo de dólar (ej: "34.990 pesos", "71.990 pesos con Santander").

CATÁLOGO DE PLANES FITLIFE GYM:
1. Plan Mensual (1 Mes): 34.990 pesos (con Santander: 27.990 pesos). Acceso libre a máquinas, cardio y todas las clases dirigidas.
2. Plan Trimestral (3 Meses): 89.990 pesos (con Santander: 71.990 pesos). Incluye escaneo InBody y pauta personalizada.
3. Plan Semestral (6 Meses): 159.990 pesos (con Santander: 127.990 pesos). Incluye 2 evaluaciones InBody, 2 pases gratis para amigos al mes y congelamiento por 15 días.
4. Plan Anual VIP (12 Meses): 279.990 pesos (con Santander: 223.990 pesos). Matrícula gratis, acceso a todas las sedes, nutricionista y congelamiento por 30 días.

BENEFICIO SANTANDER DESTACADO:
- Todos los clientes que paguen con Tarjetas Santander obtienen un 20% de descuento automático en cualquiera de los planes.

FLUJO DEL ASISTENTE:
1. Saludo / Consulta inicial:
   - Saluda brevemente y pregunta qué plan desea o en qué le puedes ayudar.
2. Solicitud de RUT:
   - Si el cliente quiere contratar, pagar o revisar su cuenta, indícale amablemente: "Por favor indícame o digita tu RUT en pantalla para asociar tu plan."
3. Consulta de Planes:
   - Si pregunta qué planes hay, nómbralos de forma concisa: "Tenemos planes por 1 mes, 3 meses, 6 meses y el plan anual de 12 meses. ¿Cuál te interesa?"
4. Confirmación de Plan y Sugerencia Santander:
   - Cuando el cliente elige un plan, confirma el valor y sugiere Santander: "¿Deseas pagar con tarjetas Santander para aprovechar un 20 por ciento de descuento u otro banco?"
5. Redirección y Modo Pago (Instrucción de Acercar Tarjeta):
   - Cuando el usuario confirma el medio de pago o banco, di la instrucción de pago: "Perfecto, te estoy redirigiendo al terminal de pago. Por favor acerca tu tarjeta o inserta tu chip en el dispositivo."
6. Confirmación de Pago Exitoso:
   - Si el sistema te indica que el pago fue aprobado: "¡Tu pago ha sido aprobado exitosamente! Tu membresía ya está activa y enviamos el comprobante a tu correo. ¿Deseas algo más?"
7. Despedida y Cierre:
   - Si el usuario dice "no", "nada más", "gracias" o se despide: "¡Muchas gracias por unirte a FitLife Gym! Que tengas un excelente día."

LÍMITE TEMÁTICO:
- SOLO responde sobre FitLife Gym, sus planes, servicios y procesos de pago.
- Si preguntan sobre programación, matemáticas o temas no relacionados, responde amablemente: "Disculpa, solo puedo asesorarte sobre las membresías y pagos de FitLife Gym. ¿En qué plan te gustaría inscribirte?"

EJEMPLOS DE INTERACCIÓN:

Cliente: "Hola, quiero saber los precios del gimnasio"
Respuesta: "¡Hola! Tenemos el Plan Mensual por 34.990 pesos, 3 meses por 89.990, 6 meses por 159.990 y el Plan Anual por 279.990 pesos. ¿Cuál prefieres?"

Cliente: "Quiero el plan de 6 meses"
Respuesta: "Excelente elección. ¿Deseas pagar con tarjetas Santander para obtener un 20 por ciento de descuento o prefieres otro banco?"

Cliente: "Pago con Santander"
Respuesta: "Perfecto, te estoy redirigiendo al terminal de pago. Por favor acerca tu tarjeta Santander al lector o inserta el chip."

Cliente: "Prefiero pagar con Banco Estado"
Respuesta: "Muy bien. Te redirijo al terminal de pago. Por favor acerca tu tarjeta al lector o inserta el chip en el dispositivo."

Cliente: "Mi RUT es 12.345.678-5"
Respuesta: "¡Hola Juan! Tu cuenta está lista. ¿Qué plan deseas contratar hoy?"
'''


def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Construye el prompt dinámico inyectando contexto específico del gimnasio
    y de la cuenta si se detecta un RUT.
    """
    clean_msg = user_msg.lower()

    # Detectar RUT en el mensaje
    rut_match = re.search(r'(\d{1,2}(?:\.?\d{3}){2}-?[\dkK])', user_msg)
    extra_context = []

    if rut_match:
        rut_found = rut_match.group(1).replace('.', '').replace('-', '').lower()
        cliente = _CLIENTES_BY_RUT.get(rut_found)
        if cliente:
            extra_context.append(f"CLIENTE IDENTIFICADO EN SISTEMA: Nombre: {cliente['nombre']}, RUT: {cliente['rut']}, Email: {cliente['email']}, Estado: {cliente['estado']}.")
        else:
            extra_context.append(f"NUEVO CLIENTE: RUT detectado: {rut_match.group(1)}. Salúdalo amablemente y dale la bienvenida como nuevo socio.")

    # Si hay contexto extra, agregarlo
    if extra_context:
        return f"{BASE_SYSTEM_PROMPT}\n" + "\n".join(extra_context)

    return BASE_SYSTEM_PROMPT


def clear_conversation(sessionid: str) -> None:
    """Elimina el historial de conversación de la sesión indicada."""
    if sessionid in _histories:
        del _histories[sessionid]
        logger.info(f"[LLM] Historial borrado para sesión: {sessionid}")
    else:
        logger.info(f"[LLM] clear_conversation: no había historial para {sessionid}")


def _get_messages_with_history(sessionid: str, user_message: str) -> list:
    """Construye la lista completa de mensajes para el LLM incluyendo el historial."""
    history = _histories.get(sessionid, [])
    dynamic_prompt = _get_dynamic_system_prompt(user_message, history)
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
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        _histories[sessionid] = history[-max_msgs:]
        logger.debug(f"[LLM] Historial recortado a {MAX_HISTORY_TURNS} turnos para sesión {sessionid}")


def llm_response(message: str, avatar_session: "BaseAvatar", datainfo: dict = {}):
    """
    Envía `message` al LLM y alimenta al avatar con la respuesta normalizada.
    Mantiene historial de conversación por sesión.
    """
    sessionid: str = datainfo.get("sessionid", "")
    try:
        start = time.perf_counter()
        logger.info(f"[LLM] Enviando mensaje (sesión={sessionid}): {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": _get_messages_with_history(sessionid, message),
            "options": {
                "num_ctx": OLLAMA_NUM_CTX,
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

        full_text: str = data["message"]["content"]
        logger.info(f"[LLM] Respuesta en {elapsed:.2f}s: {full_text[:120]}...")

        clean_text = normalizar(full_text)
        _append_to_history(sessionid, message, clean_text)

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
            "messages": _get_messages_with_history(sessionid, message),
            "options": {
                "num_ctx": OLLAMA_NUM_CTX,
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
                yield content

                if _is_cancelled(sessionid):
                    break

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        if not _is_cancelled(sessionid) and full_text.strip():
            clean_text = normalizar(full_text.strip())
            if clean_text:
                logger.info(f"[LLM Stream] -> avatar (completo fluido): {clean_text}")
                avatar_session.put_msg_txt(clean_text, datainfo)
            _append_to_history(sessionid, message, clean_text)

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s (cancelado={_is_cancelled(sessionid)}), total chars={len(full_text)}")

    except Exception as e:
        if not _is_cancelled(sessionid):
            logger.exception("[LLM Stream] Error:")
            yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"