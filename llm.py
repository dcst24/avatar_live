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

    # 2c. Reemplazo fonético para evitar 'uno mes', 'uno pago', 'uno cuota' en TTS
    text = re.sub(r'\b1\s+mes(?:es)?\b', 'un mes', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+pago\b', 'un pago', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+cuota\b', 'una cuota', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+año\b', 'un año', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+día\b', 'un día', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+evaluaci[oó]n\b', 'una evaluación', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+pase\b', 'un pase', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+escaneo\b', 'un escaneo', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+semana\b', 'una semana', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+vez\b', 'una vez', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+persona\b', 'una persona', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+socio\b', 'un socio', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1\s+cliente\b', 'un cliente', text, flags=re.IGNORECASE)
    text = re.sub(r'\b1,\s*3,\s*6\b', 'un, 3, 6', text)

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
_generation_counters: dict = {}
_generation_lock = threading.Lock()

def abort_generation(sessionid: str):
    """Marca la sesión para abortar inmediatamente cualquier streaming activo del LLM."""
    if not sessionid:
        return
    with _generation_lock:
        _generation_counters[sessionid] = _generation_counters.get(sessionid, 0) + 1
    logger.info(f"[LLM] Generación abortada para sesión: {sessionid}")

def start_new_generation(sessionid: str) -> int:
    """Inicia una nueva generación y retorna el identificador único de generación."""
    with _generation_lock:
        gen_id = _generation_counters.get(sessionid, 0) + 1
        _generation_counters[sessionid] = gen_id
        return gen_id

def _is_cancelled(sessionid: str, gen_id: int) -> bool:
    if not sessionid:
        return False
    with _generation_lock:
        return _generation_counters.get(sessionid, 0) != gen_id

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
Tu función es brindar atención al cliente, presentar los planes de gimnasio (un mes, 3 meses, 6 meses y 12 meses), asociar la cuenta mediante RUT y guiar el proceso de pago simulado.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS PARA VOZ):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones, menos de 25 palabras en total).
- El usuario te escucha hablar a través de un avatar en tiempo real. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones largas.
- NUNCA uses asteriscos (*), negritas (**), guiones (- o —), viñetas (•) ni caracteres especiales.
- Di los precios en pesos sin el signo de dólar (ej: "34.990 pesos", "71.990 pesos con Santander").
- REGLA DE PRONUNCIACIÓN: Escribe SIEMPRE "un mes" o "un pago" con palabras (NUNCA "1 mes" ni "1 pago") para evitar que el avatar pronuncie "uno mes".

CATÁLOGO DE PLANES FITLIFE GYM:
1. Plan Mensual (un mes): 34.990 pesos (con Santander: 27.990 pesos). Acceso libre a máquinas, cardio y todas las clases dirigidas.
2. Plan Trimestral (3 Meses): 89.990 pesos (con Santander: 71.990 pesos). Incluye escaneo InBody y pauta personalizada.
3. Plan Semestral (6 Meses): 159.990 pesos (con Santander: 127.990 pesos). Incluye 2 evaluaciones InBody, 2 pases gratis para amigos al mes y congelamiento por 15 días.
4. Plan Anual VIP (12 Meses): 279.990 pesos (con Santander: 223.990 pesos). Matrícula gratis, acceso a todas las sedes, nutricionista y congelamiento por 30 días.

MODALIDADES DE PAGO Y CUOTAS DISPONIBLES:
- Un pago al contado (sin cuotas).
- 3 Cuotas Sin Interés.
- 6 Cuotas Sin Interés.
- Hasta 12 Cuotas (con Tarjetas Santander 12 cuotas sin interés y 20% de descuento).

BENEFICIO SANTANDER DESTACADO:
- Todos los clientes que paguen con Tarjetas Santander obtienen un 20% de descuento automático en cualquiera de los planes y hasta 12 cuotas sin interés.

FLUJO DEL ASISTENTE:
1. Saludo / Presentación inicial:
   - Cuando el usuario salude ("Hola", "Buenas", etc.):
     Preséntate como asistente virtual de FitLife Gym y ofrece mostrar los planes:
     "¡Hola! Soy tu asistente virtual de FitLife Gym. ¿Te gustaría conocer nuestros planes y membresías?"
2. Solicitud de RUT:
   - Si el cliente quiere contratar, pagar o revisar su cuenta, indícale amablemente: "Por favor indícame o digita tu RUT en pantalla para asociar tu plan."
3. Consulta de Planes o Precios:
   - Si pregunta qué planes hay o los precios, nómbralos de forma concisa: "Tenemos planes por un mes, 3 meses, 6 meses y el plan anual de 12 meses. ¿Cuál te interesa?"
 4. Confirmación de Plan y Selección de Medio de Pago:
   - Cuando el cliente elige un plan, confirma la elección y dile que seleccione su medio de pago:
     "Excelente elección. Por favor selecciona tu medio de pago en la pantalla. Recuerda que con tarjetas Santander tienes un 20 por ciento de descuento."
 5. Selección de Medio de Pago y Redirección al POS:
   - Cuando el cliente indica el banco o medio de pago (ej. Santander, Banco de Chile, BancoEstado, Débito, Crédito):
     Confirma el banco elegido y da la instrucción de pago en el POS:
     "Excelente. Te estoy redirigiendo al terminal de pago POS. Por favor acerca tu tarjeta al lector o inserta tu chip para completar la transacción."
 6. Confirmación de Pago Exitoso:
   - Si el sistema indica que el pago fue aprobado: "¡Tu pago ha sido aprobado exitosamente en el POS Getnet! Tu membresía ya está activa y hemos enviado el comprobante a tu correo. ¿Deseas algo más en lo que pueda ayudarte?"
 7. Agradecimiento y Cierre de Interacción:
   - Si el usuario dice "gracias", "muchas gracias", "no gracias", "nada más", "no", "nada", "eso es todo" o "chao":
     "¡De nada! Tu plan ya está listo. Si necesitas algo más, aquí estaré para ayudarte. ¡Que tengas un excelente día!"

LÍMITE TEMÁTICO:
- SOLO responde sobre FitLife Gym, sus planes, servicios y procesos de pago.
- Si preguntan sobre programación, matemáticas o temas no relacionados, responde amablemente: "Disculpa, solo puedo asesorarte sobre las membresías y pagos de FitLife Gym. ¿En qué plan te gustaría inscribirte?"

EJEMPLOS DE INTERACCIÓN:

Cliente: "Hola"
Respuesta: "¡Hola! Soy tu asistente virtual de FitLife Gym. ¿Te gustaría conocer nuestros planes y membresías?"

Cliente: "Sí muéstrame" o "Quiero saber los precios"
Respuesta: "Tenemos planes por un mes a 34.990 pesos, 3 meses a 89.990, 6 meses a 159.990 y anual a 279.990 pesos. ¿Cuál te interesa?"

Cliente: "Quiero el plan de 6 meses"
Respuesta: "Excelente elección, el Plan Semestral de 6 meses. Por favor selecciona tu medio de pago en pantalla. Con Santander tienes 20 por ciento de descuento."

Cliente: "El de un mes"
Respuesta: "Excelente, el Plan Mensual por un mes. Por favor selecciona tu medio de pago en pantalla."

Cliente: "Pago con Santander"
Respuesta: "Perfecto, con Banco Santander. Te estoy redirigiendo al terminal de pago. Por favor acerca tu tarjeta al lector o inserta tu chip."

Cliente: "Con Banco de Chile"
Respuesta: "Muy bien, con Banco de Chile. Te redirijo al terminal de pago. Por favor acerca tu tarjeta al lector o inserta el chip."

Cliente: "No gracias, nada más" o "Gracias"
Respuesta: "¡De nada! Si necesitas algo más, aquí estaré para ayudarte. ¡Que tengas un excelente día!"
'''



def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Construye el prompt dinámico inyectando contexto específico del gimnasio
    y de la cuenta si se detecta un RUT o cuotas.
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

    # Detectar plan mencionado en el mensaje
    if re.search(r'\b(12\s*meses?|doce\s*meses?|anual|vip|un\s*a[nñ]o)\b', clean_msg):
        extra_context.append("PLAN ELEGIDO POR EL CLIENTE: Plan Anual VIP (12 Meses) - Precio 279.990 pesos (con Santander 20% OFF: 223.990 pesos).")
    elif re.search(r'\b(6\s*meses?|seis\s*meses?|semestral)\b', clean_msg):
        extra_context.append("PLAN ELEGIDO POR EL CLIENTE: Plan Semestral (6 Meses) - Precio 159.990 pesos (con Santander 20% OFF: 127.990 pesos).")
    elif re.search(r'\b(3\s*meses?|tres\s*meses?|trimestral)\b', clean_msg):
        extra_context.append("PLAN ELEGIDO POR EL CLIENTE: Plan Trimestral (3 Meses) - Precio 89.990 pesos (con Santander 20% OFF: 71.990 pesos).")
    elif re.search(r'\b(1\s*mes|un\s*mes|mensual)\b', clean_msg):
        extra_context.append("PLAN ELEGIDO POR EL CLIENTE: Plan Mensual (un mes) - Precio 34.990 pesos (con Santander 20% OFF: 27.990 pesos).")

    # Detectar cuotas explícitas en el mensaje del usuario (12 primero, luego 6, luego 3, luego 1)
    if re.search(r'\b(12\s*cuotas?|doce\s*cuotas?)\b', clean_msg):
        extra_context.append("MODALIDAD DE PAGO ELEGIDA POR EL CLIENTE: 12 cuotas sin interés con Santander. Confirma 'en 12 cuotas sin interés con Santander' y redirige al terminal.")
    elif re.search(r'\b(6\s*cuotas?|seis\s*cuotas?)\b', clean_msg):
        extra_context.append("MODALIDAD DE PAGO ELEGIDA POR EL CLIENTE: 6 cuotas sin interés. Confirma 'en 6 cuotas sin interés' y redirige al terminal.")
    elif re.search(r'\b(3\s*cuotas?|tres\s*cuotas?)\b', clean_msg):
        extra_context.append("MODALIDAD DE PAGO ELEGIDA POR EL CLIENTE: 3 cuotas sin interés. Confirma 'en 3 cuotas sin interés' y redirige al terminal.")
    elif re.search(r'\b(1\s*cuota|una\s*cuota|al\s*contado|un\s*pago|sin\s*cuotas?|0\s*cuotas?|solo\s*1|solo\s*una)\b', clean_msg):
        extra_context.append("MODALIDAD DE PAGO ELEGIDA POR EL CLIENTE: 1 pago al contado. Confirma 'en un pago al contado' y redirige al terminal.")

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
    gen_id = start_new_generation(sessionid) if sessionid else 0
    try:
        start = time.perf_counter()
        logger.info(f"[LLM Stream] Enviando mensaje (sesión={sessionid}, gen={gen_id}): {message}")

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
            if _is_cancelled(sessionid, gen_id):
                logger.info(f"[LLM Stream] Cancelación detectada en iteración para sesión: {sessionid} (gen={gen_id})")
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

                if _is_cancelled(sessionid, gen_id):
                    break

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        if not _is_cancelled(sessionid, gen_id) and full_text.strip():
            clean_text = normalizar(full_text.strip())
            if clean_text:
                logger.info(f"[LLM Stream] -> avatar (completo fluido): {clean_text}")
                avatar_session.put_msg_txt(clean_text, datainfo)
            _append_to_history(sessionid, message, clean_text)

        elapsed = time.perf_counter() - start
        cancelled = _is_cancelled(sessionid, gen_id)
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s (cancelado={cancelled}), total chars={len(full_text)}")

    except Exception as e:
        if not _is_cancelled(sessionid, gen_id):
            logger.exception("[LLM Stream] Error:")
            yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"