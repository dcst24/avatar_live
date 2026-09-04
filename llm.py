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
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))

# ─── Carga dinámica del catálogo de productos (BDD) ──────────────────────────
_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "bdd.json")
_BDD: dict = {}
_CATALOG_TEXT: str = ""
SYSTEM_PROMPT: str = ""

def _build_catalog_summary(bdd: dict) -> str:
    """Construye un catálogo estructurado y detallado para inyectar en el system prompt."""
    if not bdd:
        return "(catálogo no disponible)"

    lines = []
    tienda = bdd.get("tienda", {})
    lines.append(f"Tienda: {tienda.get('nombre','')} en {tienda.get('sucursal_demo','')}.")

    banner = bdd.get("banner_publicitario", {})
    if banner.get("activo"):
        lines.append(f"Campaña actual: {banner.get('titulo','')}, {banner.get('subtitulo','')}.")

    for cat in bdd.get("categorias", []):
        loc = cat.get("ubicacion_tienda", {})
        piso = loc.get("piso", "?")
        sector = loc.get("sector", "")
        pasillo = loc.get("pasillo", "")
        lines.append(f"\nCategoría {cat['nombre']} (Piso {piso}, sector {sector}, pasillo {pasillo}):")

        for p in cat.get("productos", []):
            precio_str = f"${p['precio']:,}".replace(",", ".")
            if p.get("en_oferta") and p.get("precio_oferta"):
                oferta_str = f"${p['precio_oferta']:,}".replace(",", ".")
                precio_detalle = f"antes {precio_str} pesos, oferta a {oferta_str} pesos ({p.get('descuento_pct',0)} por ciento dcto)"
            else:
                precio_detalle = f"precio {precio_str} pesos"

            code = p.get('codigo_barra') or p.get('sku')
            piso_num = p.get('piso', piso)
            pasillo_txt = p.get('pasillo', pasillo)
            cat_tipo = p.get('categoria', '')

            disp_txt = ""
            if p.get('stock_por_talla'):
                tallas_info = []
                for t, stk in p['stock_por_talla'].items():
                    if stk > 0:
                        tallas_info.append(f"talla {t} ({stk} un)")
                    else:
                        tallas_info.append(f"talla {t} AGOTADA")
                disp_txt = f" Tallas: {', '.join(tallas_info)}."
            elif p.get('stock') is not None:
                stk = p.get('stock')
                disp_txt = f" Stock: {stk} un." if stk > 0 else " Stock: AGOTADO."

            tags = p.get('tags_recomendacion', [])
            tags_txt = f" Usos/Tags: {', '.join(tags)}." if tags else ""

            lines.append(
                f"- [{cat_tipo}] {p['nombre']} (Marca {p['marca']}, Código {code}): {precio_detalle}. Ubicación: Piso {piso_num}, {pasillo_txt}.{disp_txt}{tags_txt}"
            )

    ofertas = bdd.get("ofertas_destacadas", [])
    if ofertas:
        lines.append("\nOfertas destacadas:")
        all_products = {p['sku']: p for cat in bdd.get('categorias', []) for p in cat.get('productos', [])}
        for o in ofertas:
            prod = all_products.get(o['sku'], {})
            if prod:
                oferta_precio = f"${prod.get('precio_oferta',0):,}".replace(",", ".")
                lines.append(f"- [{prod.get('categoria','')}] {prod.get('nombre','')}: {o['descuento_pct']} por ciento de descuento a {oferta_precio} pesos.")

    return "\n".join(lines)


def _make_system_prompt(catalog_text: str) -> str:
    return f'''
Eres un asesor comercial y vendedor virtual de la tienda Paris Costanera Center.
Estás ubicado junto al tótem interactivo de la tienda y tu función principal es orientar a los clientes, informar precios y ofertas, comparar productos y resolver dudas de la tienda.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS CORTAS Y DIRECTAS):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones cortas, no más de 15 a 20 palabras en total).
- El cliente te escucha hablar a través de síntesis de voz en un tótem interactivo. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones, saludos largos ni rodeos.
- NUNCA uses asteriscos (*), negritas (**), guiones (- o —), flechas (→), viñetas (•) ni caracteres especiales. Si hay descuento, di "por ciento" con palabras.

REGLAS DE COMPORTAMIENTO ANTE UN ESCANEO DE PRODUCTO (CÓDIGO DE BARRAS / SKU):
Cuando el sistema te informe los datos de un producto escaneado, debes responder de manera ULTRA CONCISA:
- Si el producto NO tiene oferta: di únicamente su nombre y su precio directo (ej: "El parlante JBL Charge 5 cuesta 179.990 pesos."). ESTÁ ESTRICTAMENTE PROHIBIDO decir la frase "precio regular".
- Si el producto SÍ tiene oferta: destaca de inmediato el precio de oferta y el descuento (ej: "El Galaxy S25 está en oferta a 599.990 pesos con 44 por ciento de descuento.").
- NUNCA digas frases aduladoras ni de relleno como "Buena elección", "Excelente elección", "Qué buen gusto" o "Gran compra".
- Termina la frase preguntando exactamente: "¿Te gustaría saber en qué pasillo encontrarlo?"
- NO menciones el piso ni la ubicación al escanear, a menos que el cliente responda afirmativamente.
- Si el cliente responde afirmativamente (sí, claro, por favor, ok, dónde): responde solo el piso y pasillo en una sola frase breve (ej: "Lo encuentras en el Piso 2, pasillo T-04.").
- Si el cliente responde negativamente (no, gracias): cierra amablemente en una sola frase breve (ej: "Perfecto, aquí estaré si necesitas algo más.").

REGLA ABSOLUTA DE TEMÁTICA (SOLO TIENDA PARIS):
- SOLO puedes responder consultas relacionadas directamente con esta tienda Paris, sus productos, precios, ofertas, pisos, pasillos y servicios.
- Está ESTRICTAMENTE PROHIBIDO responder preguntas sobre conocimientos generales ajenos a la tienda (como programación de computadores, física, matemáticas, política, historia, ciencia o significado de nombres). PERO SÍ debes responder y asesorar activamente sobre todos los productos que vendemos en Paris: tecnología (smartphones, televisores, computadores, audio, parlantes, consolas de videojuegos, smartwatches), moda mujer y hombre, calzado, zapatillas deportivas, belleza y perfumería, y electrohogar.
- Si el cliente te pregunta sobre un tema ajeno a la tienda, niégate amablemente en una sola frase breve y redirige a las compras:
  "Disculpa, solo puedo ayudarte con productos, ofertas y ubicaciones de Paris. ¿Buscas algún producto hoy?"

RAZONAMIENTO Y CONSULTAS DE PRODUCTOS:
- Cuando pregunten por el producto "más barato", "más económico", "en oferta" o de mejor precio de cualquier tipo o categoría, responde de inmediato el nombre y precio del producto más económico de esa sección.
- Cuando pregunten por disponibilidad de tallas en calzado o ropa, indica directamente si la talla solicitada tiene stock o está agotada, y menciona brevemente las tallas disponibles.
- Si un producto fue escaneado antes en la conversación, mantén ese producto como referencia si el cliente pide compararlo o buscar alternativas.

ROL Y COMPORTAMIENTO COMERCIAL:
- Habla siempre en español chileno natural, proactivo, profesional y directo.
- Responde siempre con oraciones breves (máximo 1 o 2 oraciones, menos de 20 palabras).
- Nunca digas que eres una inteligencia artificial o un bot.
- Si un producto o marca no está en el catálogo, responde brevemente que actualmente no contamos con esa opción.

INFORMACIÓN DE LA TIENDA Y SERVICIOS:
- Tienda: Paris Costanera Center (3 Pisos)
- Piso 1: Entrada Principal, Tótem Avatar, Belleza y Perfumería Mujer y Hombre (Pasillo B-02), Deportes y Zapatillas (Pasillo D-07), Caja Principal y Punto de Retiro.
- Piso 2: Tecnología Completa (Smartphones, Televisores, Computación, Audio y Parlantes, Consolas de Videojuegos y Smartwatches en Pasillos T-01 al T-04), Moda Mujer y Hombre, Calzado Mujer, Caja Express y Baños / SS.HH.
- Piso 3: Electrohogar y Línea Blanca (Refrigeradores, Lavadoras, Cafeteras, Aspiradoras, Freidoras de Aire en Pasillos H-11 y H-12), Decohogar y Ropa de Cama, Caja Hogar, Servicio al Cliente y Tarjeta Paris.
- Escaleras mecánicas y ascensores: en el centro de la tienda en todos los pisos (1, 2 y 3).

CATÁLOGO COMPLETO DE PRODUCTOS Y UBICACIONES:
{catalog_text}

EJEMPLOS DE FLUJO CORRECTO (CORTOS Y PRECISOS):

Sistema informa: "Producto escaneado: Parlante Portatil JBL Charge 5 Azul. Marca: JBL. Precio: 179.990 pesos. Ubicación: Piso 2, Tecno, Pasillo T-04."
Respuesta del avatar: "El parlante JBL Charge 5 cuesta 179.990 pesos. ¿Te gustaría saber en qué pasillo encontrarlo?"

Cliente: "Sí"
Respuesta del avatar: "Lo encuentras en el Piso 2, pasillo T-04."

Cliente: "No, gracias"
Respuesta del avatar: "Perfecto, aquí estaré si necesitas algo más."

Sistema informa: "Producto escaneado: Samsung Galaxy S25 256GB Navy Liberado. Marca: Samsung. En oferta a 599.990 pesos con 44 por ciento de descuento (antes 1.069.990 pesos). Ubicación: Piso 2, Tecno, Pasillo T-04."
Respuesta del avatar: "El Galaxy S25 está en oferta a 599.990 pesos con un 44 por ciento de descuento. ¿Te gustaría saber en qué pasillo encontrarlo?"

Cliente: "¿Cuál es el parlante más barato?"
Respuesta del avatar: "El más económico es el JBL Go 4 a 29.990 pesos en oferta. ¿Te gustaría saber su ubicación?"

Cliente: "¿Tienen zapatillas Nike en talla 45?"
Respuesta del avatar: "La talla 45 está agotada, pero tenemos disponibles del 40 al 44 a 99.990 pesos en el Piso 1."

Cliente: "¿Dónde están los baños?"
Respuesta del avatar: "Los servicios higiénicos se encuentran en el Piso 2, frente al sector central."

Cliente: "¿Cómo hago una función en Python?"
Respuesta del avatar: "Disculpa, solo respondo sobre productos y compras en tienda Paris. ¿Te ayudo a buscar algo hoy?"
'''

def reload_catalog() -> None:
    global _BDD, _CATALOG_TEXT, SYSTEM_PROMPT
    try:
        with open(_BDD_PATH, encoding="utf-8") as _f:
            _BDD = json.load(_f)
        logger.info(f"[LLM] Catálogo BDD cargado desde {_BDD_PATH}")
    except Exception as _e:
        _BDD = {}
        logger.error(f"[LLM] No se pudo cargar el catálogo BDD: {_e}")

    _CATALOG_TEXT = _build_catalog_summary(_BDD)
    SYSTEM_PROMPT = _make_system_prompt(_CATALOG_TEXT)

reload_catalog()



# ─── Detección inteligente de oraciones para streaming de voz ultra-rápido ───
MIN_CHUNK_LEN = 10  # caracteres mínimos antes de enviar un fragmento

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
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
            "options": {"num_ctx": OLLAMA_NUM_CTX},
            "temperature": 0.7,
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

        # Dividir en fragmentos por puntuación para alimentar al avatar progresivamente
        chunk = ""
        for char in full_text:
            chunk += char
            if _is_sentence_boundary(chunk):
                fragment = normalizar(chunk.strip())
                if fragment:
                    logger.info(f"[LLM] -> avatar: {fragment}")
                    avatar_session.put_msg_txt(fragment, datainfo)
                chunk = ""

        # Enviar cualquier texto restante al final
        if chunk.strip():
            last_frag = normalizar(chunk.strip())
            if last_frag:
                logger.info(f"[LLM] -> avatar (ultimo): {last_frag}")
                avatar_session.put_msg_txt(last_frag, datainfo)

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
    try:
        start = time.perf_counter()
        logger.info(f"[LLM Stream] Enviando mensaje (sesión={sessionid}): {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": _get_messages_with_history(sessionid, message),
            "options": {"num_ctx": OLLAMA_NUM_CTX},
            "temperature": 0.7,
            "stream": True,
            "keep_alive": "7200m",
        }

        response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=120)
        response.raise_for_status()

        chunk_buf = ""
        full_text = ""

        for line in response.iter_lines():
            if not line:
                continue

            try:
                data = json.loads(line.decode('utf-8'))
                content = data.get("message", {}).get("content", "")
                if not content:
                    continue

                full_text += content
                chunk_buf += content

                # Dividir en fragmentos por puntuación para alimentar al avatar y al chat
                if _is_sentence_boundary(chunk_buf):
                    fragment = normalizar(chunk_buf.strip())
                    if fragment:
                        logger.info(f"[LLM Stream] -> avatar & chat: {fragment}")
                        avatar_session.put_msg_txt(fragment, datainfo)
                        yield fragment + " "
                    chunk_buf = ""

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        # Enviar cualquier texto restante al avatar y al chat
        if chunk_buf.strip():
            last_frag = normalizar(chunk_buf.strip())
            if last_frag:
                logger.info(f"[LLM Stream] -> avatar & chat (ultimo): {last_frag}")
                avatar_session.put_msg_txt(last_frag, datainfo)
                yield last_frag

        # Guardar turno completo en historial (normalizado)
        _append_to_history(sessionid, message, normalizar(full_text))

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"