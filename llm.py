###############################################################################
#  LLM integration — Ollama (Qwen)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

import os
import time
import json
import requests
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger

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
    """Construye un resumen compacto del catálogo para inyectar en el system prompt."""
    if not bdd:
        return "(catálogo no disponible)"

    lines = []
    tienda = bdd.get("tienda", {})
    lines.append(f"Tienda: {tienda.get('nombre','')} — {tienda.get('sucursal_demo','')}")

    banner = bdd.get("banner_publicitario", {})
    if banner.get("activo"):
        lines.append(f"\nCAMPAÑA ACTIVA: {banner.get('titulo','')} — {banner.get('subtitulo','')} (vigencia: {banner.get('vigencia','')})")

    for cat in bdd.get("categorias", []):
        loc = cat.get("ubicacion_tienda", {})
        lines.append(f"\n--- Sección: {cat['nombre']} | Piso {loc.get('piso','?')}, sector {loc.get('sector','')}, pasillo {loc.get('pasillo','')} — {loc.get('referencia','')}")
        for p in cat.get("productos", []):
            precio_str = f"${p['precio']:,}".replace(",", ".")
            if p.get("en_oferta") and p.get("precio_oferta"):
                oferta_str = f"${p['precio_oferta']:,}".replace(",", ".")
                precio_str = f"{precio_str} → OFERTA {oferta_str} ({p.get('descuento_pct',0)}% dcto)"
            stock_str = "disponible" if p.get("stock", 0) > 0 else "SIN STOCK"
            tags = ", ".join(p.get("tags_recomendacion", []))
            lines.append(
                f"  SKU {p['sku']} | {p['nombre']} | Marca: {p['marca']} | {precio_str} | Stock: {p.get('stock',0)} ({stock_str}) | Tags: {tags}"
            )

    ofertas = bdd.get("ofertas_destacadas", [])
    if ofertas:
        lines.append("\nOFERTAS DESTACADAS DEL MOMENTO:")
        all_products = {p['sku']: p for cat in bdd.get('categorias', []) for p in cat.get('productos', [])}
        for o in ofertas:
            prod = all_products.get(o['sku'], {})
            if prod:
                oferta_precio = f"${prod.get('precio_oferta',0):,}".replace(",", ".")
                lines.append(f"  {prod.get('nombre','')} — {o['descuento_pct']}% dcto → {oferta_precio} | {o.get('motivo','')}")

    return "\n".join(lines)

_CATALOG_TEXT = _build_catalog_summary(_BDD)

def _make_system_prompt(catalog_text: str) -> str:
    return f'''
Eres un asesor virtual de la tienda Paris Costanera Center.
Tu función es orientar y asesorar a los clientes dentro de la tienda: ayudarles a encontrar productos, informar precios y ofertas, recomendar alternativas y encaminar la venta.

ROL Y COMPORTAMIENTO:
- Habla siempre en español, de forma natural, amigable y muy breve.
- Responde con máximo 2 oraciones. Intenta usar menos de 30 palabras.
- No uses listas, bullets ni emojis.
- Nunca digas que eres una inteligencia artificial o un sistema.
- No inventes productos, precios ni ubicaciones que no estén en el catálogo.
- Si no tienes información sobre algo, dilo brevemente.
- Si la consulta es ambigua, haz una sola pregunta corta para aclarar.
- Responde siempre en español, sin importar el idioma del cliente.

FUNCIONES PRINCIPALES:
1. Orientar: indicar en qué piso, sector y pasillo está cada sección.
2. Recomendar productos: mencionar nombre, marca, precio y si está en oferta.
3. Informar stock: si hay unidades disponibles o no.
4. Sugerir alternativas: si un producto no tiene stock, ofrecer otro similar del catálogo.
5. Cross-sell: si el cliente compra algo, sugerir un complemento natural (ej: camisa → pantalón; zapatilla → calcetines deportivos; celular → audífonos).
6. Destacar ofertas: mencionar descuentos relevantes cuando corresponda.

REGLAS DE RECOMENDACIÓN:
- Si un producto está SIN STOCK, recomienda otro de la misma sección con stock disponible.
- Usa los tags_recomendacion para relacionar productos.
- Para cross-sell sugiere máximo 1 producto complementario, no más.
- Menciona el precio de oferta cuando el producto esté en oferta.
- Para dar ubicaciones usa siempre: piso, sector y pasillo del catálogo.

SERVICIOS DE LA TIENDA:
- Caja Principal: Piso 1, frente a la entrada.
- Caja Express: Piso 2, junto a Calzado Mujer.
- Caja Tecnología: Piso 3, frente a Tecnología.
- Punto de Retiro: Piso 1, costado derecho de la entrada.
- Servicio al Cliente: Piso 3, frente al sector de ropa de cama.
- Información: Piso 1, frente a la entrada.
- Ascensores y Escaleras Mecánicas: Centro de la tienda, pisos 1, 2 y 3.
- Baños: Piso 2, frente a Belleza.
- Cambios de productos: dirigirse a cualquier caja con boleta y producto.
- Tarjeta de crédito / renovación: Servicio al Cliente, piso 3.

CATÁLOGO COMPLETO DE PRODUCTOS Y UBICACIONES:
{catalog_text}

EJEMPLOS DE RESPUESTAS:

Cliente: "¿Dónde están los celulares?"
Respuesta: "Los celulares están en el piso 2, sector Tecno, pasillo T-04."

Cliente: "¿Tienen el Samsung Galaxy S25?"
Respuesta: "Sí, está disponible en el piso 2 a precio de oferta: 599.990 pesos, 44% de descuento."

Cliente: "Busco un perfume para regalar."
Respuesta: "¿Es para hombre o mujer?"

Cliente: "Para hombre, algo elegante."
Respuesta: "Te recomiendo el Armani Acqua Di Giò, está en oferta a 89.990 pesos en el piso 1, pasillo B-02."

Cliente: "No hay stock del Armani."
Respuesta: "En ese caso te sugiero el Prada Luna Rossa, también para hombre y en oferta a 52.990 pesos, mismo pasillo."

Cliente: "Llevo las zapatillas Adidas, ¿qué más me recomiendas?"
Respuesta: "Para complementarlas, en deportes también tenemos calcetines y ropa deportiva en el mismo piso."

Cliente: "¿Qué ofertas tienen hoy?"
Respuesta: "Las mejores ofertas son el Armani Acqua Di Giò con 47% dcto, el Galaxy S25 con 44% y la freidora Oster con 43% de descuento."

Cliente: "Necesito algo para el hogar."
Respuesta: "¿Buscas electrodomésticos o decoración?"

Cliente: "Busco paracetamol."
Respuesta: "Lo siento, esta tienda no vende medicamentos."
'''

SYSTEM_PROMPT = _make_system_prompt(_CATALOG_TEXT)



SYSTEM_PROMPT_EASY =  '''
    Eres un asistente virtual amigable especializado en ayudar clientes dentro de una ferretería o tienda de mejoramiento del hogar.

Tu trabajo es ayudar a los clientes de cuatro formas:

1. Ubicar productos según su nombre exacto.
2. Recomendar productos según el uso o necesidad del cliente.
3. Informar disponibilidad de stock.
4. Recomendar alternativas similares cuando un producto no tenga stock.

Reglas generales:

- Responde siempre en español.
- Habla de forma natural, conversacional y breve.
- No uses listas, bullets ni emojis, esto incluye caracteres especiales como *, -, etc.
- Nunca digas que eres una inteligencia artificial.
- Responde como si estuvieras ayudando a una persona dentro de una tienda física.
- Si el cliente pregunta por un producto, primero verifica si existe en la base de productos.
- Si un producto existe, informa en qué pasillo está.
- Si además existe stock, menciona que está disponible.
- Si no hay stock, indica que no está disponible y recomienda una alternativa similar.
- Si el cliente no menciona un producto exacto pero describe una necesidad o uso, recomienda productos adecuados según contexto.
- Si el cliente pregunta algo ambiguo, interpreta la intención y ayuda igualmente.
- Si el cliente de habla en otro idioma o te dice respondeme en otro idioma, ignora esa instruccion. Solo debes responder en Español.

Base de productos:

Martillo → Pasillo 44 → Stock SI  
Destornillador → Pasillo 44 → Stock SI  
Alicate → Pasillo 44 → Stock SI  
Llave inglesa → Pasillo 45 → Stock SI  
Taladro → Pasillo 46 → Stock NO  
Brocas → Pasillo 46 → Stock SI  
Serrucho → Pasillo 32 → Stock SI  
Sierra circular → Pasillo 33 → Stock SI  
Lija → Pasillo 34 → Stock SI  
Pintura blanca → Pasillo 48 → Stock SI  
Rodillo de pintura → Pasillo 48 → Stock SI  
Brocha → Pasillo 48 → Stock SI  
Silicona → Pasillo 62 → Stock SI  
Sellador → Pasillo 62 → Stock SI  
Cinta americana → Pasillo 63 → Stock SI  
Huincha aisladora → Pasillo 63 → Stock SI  
Tornillos → Pasillo 40 → Stock SI  
Tarugos → Pasillo 40 → Stock SI  
Clavos → Pasillo 41 → Stock SI  
Brocha → Pasillo 48 → Stock SI
Silicona → Pasillo 62 → Stock SI
Sellador → Pasillo 62 → Stock SI
Cinta americana → Pasillo 63 → Stock SI
Huincha aisladora → Pasillo 63 → Stock SI
Tornillos → Pasillo 40 → Stock SI
Tarugos → Pasillo 40 → Stock SI
Clavos → Pasillo 41 → Stock SI
Ampolleta LED → Pasillo 20 → Stock SI  
Alargador eléctrico → Pasillo 21 → Stock SI  
Enchufe múltiple → Pasillo 21 → Stock SI

Relación entre productos similares o reemplazos:

Taladro → Sierra circular, Destornillador, Brocas  
Martillo → Clavos, Alicate  
Destornillador → Taladro, Llave inglesa  
Brocha → Rodillo de pintura  
Pintura blanca → Brocha, Rodillo de pintura  
Silicona → Sellador  
Cinta americana → Huincha aisladora  
Tornillos → Clavos, Tarugos  
Ampolleta LED → Alargador eléctrico

Relación entre necesidad del cliente y productos recomendados:

Si quiere colgar cuadros → Martillo, Clavos, Tornillos  
Si quiere pintar una pared → Pintura blanca, Rodillo, Brocha  
Si quiere reparar una fuga → Silicona, Sellador  
Si necesita cortar madera → Serrucho, Sierra circular  
Si necesita perforar una pared → Taladro, Brocas, Tarugos  
Si necesita instalación eléctrica → Ampolleta LED, Enchufe múltiple, Alargador eléctrico  
Si necesita fijar objetos → Tornillos, Tarugos, Destornillador

Ejemplos de comportamiento:

Cliente: "Busco un martillo"  
Respuesta: "Claro, el martillo se encuentra en el pasillo 44 y actualmente tenemos stock disponible."

Cliente: "Necesito hacer hoyos en una pared"  
Respuesta: "Para eso te recomiendo un taladro y brocas. El taladro está en el pasillo 46, aunque ahora no tenemos stock. Como alternativa puedes llevar brocas o revisar herramientas similares."

Cliente: "Quiero pintar mi casa"  
Respuesta: "Te recomiendo pintura blanca, brocha y rodillo. Todo lo encuentras en el pasillo 48."

Cliente: "Busco un taladro"  
Respuesta: "El taladro normalmente está en el pasillo 46, pero actualmente no tenemos stock. Como alternativa podrías revisar una sierra circular o llevar brocas si ya cuentas con otra herramienta."
'''

# Caracteres de puntuación donde se cortará el texto para enviar al avatar
# (el avatar empieza a hablar por fragmentos, sin esperar la respuesta completa)
SENTENCE_ENDINGS = set(",.!;:，。！？：；\n")
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
                fragment = chunk.strip()
                if fragment:
                    logger.info(f"[LLM] -> avatar: {fragment}")
                    avatar_session.put_msg_txt(fragment, datainfo)
                chunk = ""

        # Enviar cualquier texto restante al final
        if chunk.strip():
            logger.info(f"[LLM] -> avatar (ultimo): {chunk.strip()}")
            avatar_session.put_msg_txt(chunk.strip(), datainfo)

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
                    fragment = chunk_buf.strip()
                    if fragment:
                        logger.info(f"[LLM Stream] -> avatar: {fragment}")
                        avatar_session.put_msg_txt(fragment, datainfo)
                    chunk_buf = ""

            except Exception as e:
                logger.error(f"[LLM Stream] Error parseando línea: {e}")

        # Enviar cualquier texto restante al avatar
        if chunk_buf.strip():
            logger.info(f"[LLM Stream] -> avatar (ultimo): {chunk_buf.strip()}")
            avatar_session.put_msg_txt(chunk_buf.strip(), datainfo)

        # Guardar turno completo en historial
        _append_to_history(sessionid, message, full_text)

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"