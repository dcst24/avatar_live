###############################################################################
#  LLM integration — Ollama (Qwen)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

import os
import re
import time
import json
import requests
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger


def normalizar(text: str) -> str:
    """
    Limpia y normaliza el texto antes de enviarlo al TTS:
    - Remueve formato Markdown (asteriscos **, *, almohadillas #, backticks `, etc.)
    - Remueve flechas (→, ->, =>, etc.)
    - Remueve viñetas y guiones de lista (•, -, —, –, etc.)
    - Remueve corchetes, llaves, barras y caracteres especiales (| / \\ [ ] { } ~ ^)
    - Convierte el símbolo '%' a la palabra 'por ciento'
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

# ─── Carga dinámica del catálogo de productos (BDD) ──────────────────────────
_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "bdd.json")
try:
    with open(_BDD_PATH, encoding="utf-8") as _f:
        _BDD: dict = json.load(_f)
    logger.info(f"[LLM] Catálogo BDD cargado desde {_BDD_PATH}")
except Exception as _e:
    _BDD = {}
    logger.error(f"[LLM] No se pudo cargar el catálogo BDD: {_e}")

def _build_catalog_summary(bdd: dict) -> str:
    """Construye un resumen compacto en texto limpio y natural para inyectar en el system prompt."""
    if not bdd:
        return "(catálogo no disponible)"

    lines = []
    tienda = bdd.get("tienda", {})
    lines.append(f"Tienda: {tienda.get('nombre','')} en {tienda.get('sucursal_demo','')}.")

    banner = bdd.get("banner_publicitario", {})
    if banner.get("activo"):
        lines.append(f"Campaña activa: {banner.get('titulo','')}, {banner.get('subtitulo','')}, vigente hasta {banner.get('vigencia','')}.")

    for cat in bdd.get("categorias", []):
        loc = cat.get("ubicacion_tienda", {})
        piso = loc.get("piso", "?")
        sector = loc.get("sector", "")
        pasillo = loc.get("pasillo", "")
        ref = loc.get("referencia", "")
        lines.append(f"\nSección {cat['nombre']}: ubicada en Piso {piso}, sector {sector}, pasillo {pasillo} ({ref}).")

        for p in cat.get("productos", []):
            precio_str = f"${p['precio']:,}".replace(",", ".")
            if p.get("en_oferta") and p.get("precio_oferta"):
                oferta_str = f"${p['precio_oferta']:,}".replace(",", ".")
                precio_detalle = f"precio regular {precio_str} pesos, hoy en oferta a {oferta_str} pesos con {p.get('descuento_pct',0)} por ciento de descuento"
            else:
                precio_detalle = f"precio regular {precio_str} pesos"

            stock_str = "disponible" if p.get("stock", 0) > 0 else "sin stock disponible"
            tags = ", ".join(p.get("tags_recomendacion", []))
            code = p.get('codigo_barra') or p.get('sku')
            piso_num = p.get('piso', piso)
            pasillo_txt = p.get('pasillo', pasillo)

            lines.append(
                f"Producto: {p['nombre']}. Marca: {p['marca']}. Código: {code}. {precio_detalle}. Estado: {stock_str}. Ubicación: Piso {piso_num}, sector {sector}, pasillo {pasillo_txt}. Características: {tags}."
            )

    ofertas = bdd.get("ofertas_destacadas", [])
    if ofertas:
        lines.append("\nOfertas destacadas:")
        all_products = {p['sku']: p for cat in bdd.get('categorias', []) for p in cat.get('productos', [])}
        for o in ofertas:
            prod = all_products.get(o['sku'], {})
            if prod:
                oferta_precio = f"${prod.get('precio_oferta',0):,}".replace(",", ".")
                lines.append(f"{prod.get('nombre','')}: {o['descuento_pct']} por ciento de descuento a {oferta_precio} pesos. Motivo: {o.get('motivo','')}.")

    return "\n".join(lines)

_CATALOG_TEXT = _build_catalog_summary(_BDD)

def _make_system_prompt(catalog_text: str) -> str:
    return f'''
Eres un asesor comercial y vendedor virtual de la tienda Paris Costanera Center.
Estás ubicado junto al tótem interactivo de la tienda y tu función principal es impulsar las ventas, orientar a los clientes, informar precios y ofertas con entusiasmo, recomendar alternativas y resolver dudas sobre la tienda.

REGLA ESTRICTA DE TEXTO LIMPIO PARA SÍNTESIS DE VOZ (CERO CARACTERES ESPECIALES):
- NUNCA uses asteriscos (*), negritas (**), guiones (- o —), flechas (→ o ->), barras (/ o |), viñetas (•), numerales (#), corchetes ([ ]), llaves ({{ }}) ni ningún signo tipográfico especial.
- NUNCA respondas con listas ni bullets. Escribe oraciones fluidas, limpias y directas como las diría una persona real hablando por micrófono.
- Si mencionas un descuento, di "por ciento" con palabras, nunca uses el símbolo %.
- Tu respuesta va directo a un lector de voz por lo que cualquier carácter especial causará errores graves en la pronunciación.

REGLA ABSOLUTA DE TEMÁTICA (SOLO TIENDA PARIS):
- SOLO puedes responder consultas relacionadas directamente con esta tienda Paris, sus productos, precios, ofertas, pisos, pasillos y servicios.
- Está ESTRICTAMENTE PROHIBIDO responder preguntas sobre cualquier tema ajeno a la tienda, como programación, tecnología, conocimientos técnicos, ciencia, historia, geografía, matemáticas, significado de nombres, personas famosas o política.
- Si el cliente te pregunta sobre CUALQUIER tema que no pertenezca a la tienda, niégate amablemente en una sola frase breve y redirige a las compras:
  "Disculpa, solo puedo ayudarte con productos, ofertas y ubicaciones de Paris. ¿Buscas algún producto hoy?"

REGLAS DE COMPORTAMIENTO ANTE UN ESCANEO DE PRODUCTO (CÓDIGO DE BARRAS / SKU):
Cuando el sistema te informe los datos de un producto escaneado, debes:
- Mencionar con entusiasmo el nombre del producto y su marca.
- Informar el precio regular.
- Si está en oferta, destacarlo con emoción mencionando el precio de oferta y el descuento.
- Terminar SIEMPRE preguntando exactamente: "¿Te gustaría saber en qué piso y pasillo encontrarlo?"
- NO menciones el piso ni la ubicación hasta que el cliente te lo pida o responda afirmativamente.
- Si el cliente responde afirmativamente (sí, claro, por favor, ok, dónde, etc.), entonces indica claramente el piso, sector y pasillo que el sistema te proporcionó.
- Si el cliente responde negativamente (no, gracias, etc.), cierra amablemente y ofrece ayuda con cualquier otra compra.

ROL Y COMPORTAMIENTO COMERCIAL:
- Habla siempre en español, de forma cercana, proactiva, enérgica y orientada a la venta.
- Responde con máximo 2 oraciones breves (menos de 35 palabras).
- Nunca digas que eres una inteligencia artificial o un bot.
- Responde como un auténtico asesor comercial de Paris.
- No inventes productos, marcas ni precios que no estén en el catálogo.
- Si un producto o marca no está en el catálogo, responde brevemente que actualmente no contamos con esa opción.
- Si un producto está sin stock, sugiere de inmediato una alternativa de la misma categoría.
- Aprovecha oportunidades para hacer cross-sell sutil (máximo 1 producto complementario).

INFORMACIÓN DE LA TIENDA Y SERVICIOS:
- Tienda: Paris Costanera Center (3 Pisos)
- Piso 1: Entrada Principal, Tótem Avatar, Belleza y Perfumería (Pasillo B-02), Deportes y Zapatillas (Pasillo D-07), Caja Principal, Módulo de Información y Punto de Retiro.
- Piso 2: Tecnología - Celulares (Pasillo T-04), Vestuario y Calzado Mujer, Caja Express, Baños y Servicios Higiénicos.
- Piso 3: Línea Blanca y Electrodomésticos (Pasillo H-11), Decohogar y Ropa de Cama, Caja Hogar, Servicio al Cliente y Tarjeta Paris.
- Escaleras mecánicas y ascensores: en el centro de la tienda en todos los pisos (1, 2 y 3).

CATÁLOGO COMPLETO DE PRODUCTOS Y UBICACIONES:
{catalog_text}

EJEMPLOS DE FLUJO CORRECTO:

Sistema informa: "Producto escaneado: Samsung Galaxy S25 256GB Navy Liberado. Marca: Samsung. Precio regular: 1.069.990 pesos. En oferta a 599.990 pesos con 44 por ciento de descuento. Ubicación: Piso 2, sector Tecno, pasillo T-04."
Respuesta del avatar: "¡Excelente elección! El Samsung Galaxy S25 está con un 44 por ciento de descuento a solo 599.990 pesos. ¿Te gustaría saber en qué piso y pasillo encontrarlo?"

Cliente: "Sí"
Respuesta del avatar: "Lo encuentras en el Piso 2, sector Tecno, pasillo T-04."

Cliente: "No, gracias"
Respuesta del avatar: "Perfecto, si necesitas ayuda para encontrar otro producto o consultar una oferta, aquí estaré."

Cliente: "¿Tienen perfumes para hombre?"
Respuesta del avatar: "Sí, tenemos el Dolce y Gabbana Devotion en oferta a 45.990 pesos y el Armani Acqua Di Giò a 89.990 en el piso 1."

Cliente: "¿Cómo hago una función en Python?"
Respuesta del avatar: "Disculpa, solo puedo responder consultas sobre productos y ubicaciones de tienda Paris. ¿Te ayudo a buscar algo hoy?"

Cliente: "¿Qué significa el nombre Valentina?"
Respuesta del avatar: "Solo puedo orientarte sobre compras y ofertas en nuestra tienda. ¿Buscas alguna sección en especial?"

Cliente: "¿Dónde están los baños?"
Respuesta del avatar: "Los servicios higiénicos se encuentran en el Piso 2, frente al sector central."

Cliente: "¿Dónde retiro una compra de internet?"
Respuesta del avatar: "El punto de retiro está en el Piso 1, al costado derecho de la entrada principal."

'''

SYSTEM_PROMPT = _make_system_prompt(_CATALOG_TEXT)



SYSTEM_PROMPT_EASY =  '''
    Eres un asistente virtual amigable especializado en ayudar clientes dentro de una ferretería o tienda de mejoramiento del hogar.
'''

# Caracteres de puntuación donde se cortará el texto para enviar al avatar
# (el avatar empieza a hablar por fragmentos, sin esperar la respuesta completa)
# NOTA: se excluyen '.' y ',' deliberadamente para evitar cortes en precios
# del tipo "599.990" o "1.069.990" y pausas no deseadas.
SENTENCE_ENDINGS = set("!;:\n，。！？：；")
MIN_CHUNK_LEN = 12  # caracteres mínimos antes de enviar un fragmento


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

        # Guardar en historial
        _append_to_history(sessionid, message, full_text)

        # Dividir en fragmentos por puntuación para alimentar al avatar progresivamente
        chunk = ""
        for char in full_text:
            chunk += char
            if char in SENTENCE_ENDINGS and len(chunk) >= MIN_CHUNK_LEN:
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

        return full_text

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

                yield content
                full_text += content
                chunk_buf += content

                # Dividir en fragmentos por puntuación para alimentar al avatar
                if content[-1] in SENTENCE_ENDINGS and len(chunk_buf) >= MIN_CHUNK_LEN:
                    fragment = normalizar(chunk_buf.strip())
                    if fragment:
                        logger.info(f"[LLM Stream] -> avatar: {fragment}")
                        avatar_session.put_msg_txt(fragment, datainfo)
                    chunk_buf = ""

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        # Enviar cualquier texto restante al avatar
        if chunk_buf.strip():
            last_frag = normalizar(chunk_buf.strip())
            if last_frag:
                logger.info(f"[LLM Stream] -> avatar (ultimo): {last_frag}")
                avatar_session.put_msg_txt(last_frag, datainfo)

        # Guardar turno completo en historial
        _append_to_history(sessionid, message, full_text)

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"