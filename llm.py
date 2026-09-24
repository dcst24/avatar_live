###############################################################################
#  LLM integration — Ollama (Qwen)
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
    - Convierte precios con '$' a formato pronunciable (ej: '$599.990' -> '599.990 pesos')
    - Elimina emojis y caracteres no pronunciables
    - Colapsa espacios redundantes
    """
    if not text:
        return ""

    # 1. Reemplazar porcentajes por texto pronunciable
    text = re.sub(r'(\d+)\s*%', r'\1 por ciento', text)

    # 2. Convertir precios con signo $ a pesos (ej: $599.990 -> 599.990 pesos)
    text = re.sub(r'\$(\d[\d\.]*)\s*(?:pesos)?', r'\1 pesos', text)

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

# ─── Carga dinámica del catálogo de productos (BDD) ──────────────────────────
# ─── Carga dinámica del catálogo de productos BARPOS (BDD) ───────────────────
_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "bdd.json")
_BDD: dict = {}
_CATEGORIES_BY_ID: dict = {}
_PRODUCTS_BY_MODEL: dict = {}
_ALL_PRODUCTS: list = []

CATEGORY_KEYWORDS = {
    "lectores_codigo_barra": ["lector", "lectores", "escaner", "escáner", "pistola", "codigo", "código", "barra", "barras", "1d", "2d", "qr", "imager", "6500", "9325", "9335", "2600", "2610", "9610", "ip68s", "pedestal", "inalambrico", "inalámbrico", "bluetooth"],
    "impresoras_termicas": ["impresora", "impresoras", "termica", "térmica", "ticket", "tickets", "boleta", "boletas", "recibo", "recibos", "etiqueta", "etiquetas", "z220t", "z411t", "t8300", "zpl", "tspl", "cutter", "autocutter", "desktop"],
    "sistemas_pos": ["pos", "punto de venta", "all in one", "todo en uno", "n200s", "n200", "touch", "segunda pantalla", "pantalla touch", "computador pos"],
    "rebobinadores_etiquetas": ["rebobinador", "rebobinadora", "rebobinar", "a6", "rollo"],
    "totems_autoservicio": ["totem", "tótem", "autoservicio", "auto servicio", "auto-servicio", "ka-21a", "ka21a", "kiosko", "quiosco"]
}

def _format_category(cat: dict) -> str:
    lines = [f"\nCategoría: {cat['nombre']}:"]
    for p in cat.get("productos", []):
        lines.append(f"- {p['nombre']} (Modelo: {p['modelo']}): {p['descripcion']}")
    return "\n".join(lines)


BASE_SYSTEM_PROMPT = '''Eres un asesor técnico y comercial virtual especialista en equipamiento y productos de la marca BARPOS (Superbox).
Tu función principal es responder consultas sobre los productos BARPOS de tu catálogo, entregando la descripción y características técnicas de los equipos basándote exclusivamente en tu base de datos.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones, menos de 25 palabras en total).
- El cliente te escucha hablar a través de síntesis de voz en tiempo real. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones, saludos largos ni rodeos.
- NUNCA uses asteriscos (*), negritas (**), guiones (- o —), flechas (→), viñetas (•) ni caracteres especiales.

REGLA ESTRICTA 1 (ESTE AVATAR NO DICE UBICACIONES):
- NUNCA menciones pasillos, pisos, mapas ni ubicaciones de tiendas. Este avatar no dice ubicaciones.
- Si el usuario te pregunta por un producto, describe directamente qué es y qué características tiene según el catálogo.

REGLA ESTRICTA 2 (LÍMITE TEMÁTICO ABSOLUTO - SOLO PRODUCTOS BARPOS):
- SOLO puedes hablar sobre los productos BARPOS presentes en tu catálogo (lectores de código de barra, impresoras térmicas y de etiquetas, rebobinadores de etiquetas, sistemas POS All in One y tótems de autoservicio).
- Está ESTRICTAMENTE PROHIBIDO responder sobre programación de software (código Python, JavaScript, HTML, etc.), matemáticas, historia, ciencia, política, clima o cualquier tema externo ajeno al catálogo.
- Si el cliente pregunta sobre cualquier tema ajeno a los productos BARPOS o sobre programación, niégate amablemente en una sola frase breve y redirige a los productos BARPOS:
  "Disculpa, solo puedo entregarte información y descripciones sobre nuestros productos BARPOS. ¿Sobre qué modelo o equipo deseas consultar?"

ROL Y COMPORTAMIENTO:
- Habla en español natural, profesional y seguro.
- Entrega las especificaciones clave del producto consultado: tipo de equipo, conectividad, resolución o velocidad, accesorios incluidos y garantía.
- Nunca digas que eres una inteligencia artificial o un bot.

EJEMPLOS DE FLUJO CORRECTO:

Cliente: "¿Qué es el BARPOS 6500?"
Respuesta del avatar: "El BARPOS 6500 es un lector imager para códigos 1D y 2D QR con cable USB, pedestal manos libres y 12 meses de garantía."

Cliente: "¿Qué características tiene el 9325?"
Respuesta del avatar: "El BARPOS 9325 es un lector inalámbrico Bluetooth con tecnología imager para códigos 1D y 2D, dongle USB y cable tipo C."

Cliente: "¿Tienen impresoras térmicas?"
Respuesta del avatar: "Sí, tenemos la impresora de boletas T8300 de 300 milímetros por segundo y modelos de etiquetas como la Z220T. ¿Cuál necesitas?"

Cliente: "Háblame del lector industrial IP68S"
Respuesta del avatar: "El IP68S es un lector inalámbrico industrial con clasificación IP65 resistente a caídas y temperaturas extremas, con cuna de carga incluida."

Cliente: "¿Qué es el KA-21A?"
Respuesta del avatar: "Es un tótem de autoservicio todo en uno con pantalla táctil de 21,5 pulgadas, pedestales de piso y mesón y lector de códigos 2D integrado."

Cliente: "¿Tienen sistemas POS?"
Respuesta del avatar: "Sí, contamos con el POS N200S All in One de 15 pulgadas y la versión N200S 2 con doble pantalla y lector QR."

Cliente: "¿Cómo hago un bucle for en Python?"
Respuesta del avatar: "Disculpa, solo puedo entregarte información y descripciones sobre nuestros productos BARPOS. ¿Sobre qué modelo o equipo deseas consultar?"
'''

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Selecciona e inyecta de forma ultraligera el contexto del catálogo BARPOS
    relevante para la consulta del usuario.
    """
    user_search = user_msg.lower()

    # 1. Detectar si el usuario pregunta por un producto o modelo específico
    matched_prods = []
    for p in _ALL_PRODUCTS:
        m = p.get("modelo", "").lower()
        n = p.get("nombre", "").lower()
        if m and (m in user_search or f" {m} " in f" {user_search} "):
            matched_prods.append(p)
        elif n and n in user_search:
            matched_prods.append(p)

    # 2. Detectar categorías relevantes
    matched_cats = set()
    for cid, kws in CATEGORY_KEYWORDS.items():
        if any(kw in user_search for kw in kws):
            matched_cats.add(cid)

    # Si hay productos específicos encontrados, agregar su categoría
    for p in matched_prods:
        if p.get("categoria_id"):
            matched_cats.add(p["categoria_id"])

    # 3. Construir contexto
    extra_lines = []
    if matched_prods:
        extra_lines.append("PRODUCTO CONSULTADO DIRECTAMENTE:")
        for p in matched_prods:
            extra_lines.append(f"- {p['nombre']}: {p['descripcion']}")

    if matched_cats:
        for cid in matched_cats:
            if cid in _CATEGORIES_BY_ID:
                extra_lines.append(_format_category(_CATEGORIES_BY_ID[cid]))

    if not extra_lines:
        # Si no se detectó un modelo específico, inyectar el catálogo completo (son solo 17 productos)
        for cat in _BDD.get("categorias", []):
            extra_lines.append(_format_category(cat))

    catalog_context = "\n".join(extra_lines)
    return f"{BASE_SYSTEM_PROMPT}\nCATÁLOGO OFICIAL BARPOS:\n{catalog_context}"


def reload_catalog() -> None:
    global _BDD, _CATEGORIES_BY_ID, _ALL_PRODUCTS, _PRODUCTS_BY_MODEL
    try:
        with open(_BDD_PATH, encoding="utf-8") as _f:
            _BDD = json.load(_f)
        _CATEGORIES_BY_ID = {c["id"]: c for c in _BDD.get("categorias", [])}
        _ALL_PRODUCTS = _BDD.get("productos", [])
        _PRODUCTS_BY_MODEL = {p["modelo"].lower(): p for p in _ALL_PRODUCTS if "modelo" in p}
        logger.info(f"[LLM] Catálogo BARPOS cargado desde {_BDD_PATH} ({len(_CATEGORIES_BY_ID)} categorías, {len(_ALL_PRODUCTS)} productos)")
    except Exception as _e:
        _BDD = {}
        _CATEGORIES_BY_ID = {}
        _ALL_PRODUCTS = []
        _PRODUCTS_BY_MODEL = {}
        logger.error(f"[LLM] No se pudo cargar el catálogo BDD: {_e}")

reload_catalog()



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
    # Recortar: conservar sólo los últimos MAX_HISTORY_TURNS turnos (2 mensajes por turno)
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        _histories[sessionid] = history[-max_msgs:]
        logger.debug(f"[LLM] Historial recortado a {MAX_HISTORY_TURNS} turnos para sesión {sessionid}")


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
            "messages": _get_messages_with_history(sessionid, message),
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
            "messages": _get_messages_with_history(sessionid, message),
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