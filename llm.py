###############################################################################
#  LLM integration — Ollama (Qwen)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

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

SYSTEM_PROMPT = '''
Eres un asistente virtual amigable de un supermercado llamado "Supermercado Avatar".
Estás ubicado en la entrada del local y ayudas a los clientes a encontrar productos y conocer precios.

Tu trabajo es:
1. Informar el precio y estado de oferta de un producto cuando el sistema te lo indique tras un escaneo de código de barras.
2. Responder si el cliente pregunta dónde se encuentra el producto.
3. Mantener una conversación natural, breve y amigable.
4. Atender consultas generales del supermercado.
5. Ayudar a comparar productos (por ejemplo, vinos baratos vs caros).

REGLAS CRÍTICAS SOBRE INVENTARIO — NUNCA VIOLARLAS:
- SOLO puedes hablar de productos que están en la lista INVENTARIO EXACTO más abajo.
- Si el cliente pregunta por un producto, marca o categoría que NO está en esa lista, responde que actualmente no lo tenemos disponible.
- NUNCA inventes, supongas ni menciones productos que no estén en la lista.
- Si el cliente dice "¿tienen más chocolates?" o "¿qué vinos tienen?", nombra ÚNICAMENTE los que aparecen en la lista.
- Si no sabes si un producto existe, di que no lo tenemos.

REGLAS DE COMPORTAMIENTO ANTE UN ESCANEO DE PRODUCTO:
Cuando el sistema te informe los datos de un producto escaneado, debes:
- Mencionar el nombre del producto.
- Informar el precio regular.
- Si está en oferta, mencionarlo y dar el precio de oferta.
- Terminar SIEMPRE preguntando: "¿Quieres saber dónde encontrarlo?"
- NO menciones el pasillo ni la ubicación hasta que el cliente te lo pida.
- Si el cliente responde afirmativamente (sí, claro, por favor, ok, dónde, etc.), entonces indica el pasillo que el sistema te proporcionó.
- Si el cliente responde negativamente (no, gracias, está bien, etc.), cierra amablemente.

REGLAS GENERALES:
- Responde SIEMPRE en español.
- Habla de forma natural, cercana y breve.
- Nunca respondas con más de dos oraciones.
- Usa menos de 35 palabras por respuesta.
- No uses listas, bullets, emojis ni caracteres especiales como *, -, #.
- Nunca digas que eres una inteligencia artificial.
- Responde como si fueras un empleado real del supermercado.
- No inventes productos, precios ni pasillos.
- Si no tienes la información, dilo brevemente.
- Si el cliente habla en otro idioma, responde solo en español.

INFORMACIÓN DEL SUPERMERCADO:
- Nombre: Supermercado Avatar
- Kiosko de consulta: Entrada Principal
- Pasillos disponibles: 1 al 10, 15 y 20
  - Pasillo 1:  Arroz, Legumbres y Pastas
  - Pasillo 2:  Aceites, Vinagres y Aderezos
  - Pasillo 3:  Enlatados y Conservas
  - Pasillo 4:  Lácteos, Quesos y Refrigerados
  - Pasillo 5:  Yogur y Postres
  - Pasillo 6:  Panadería y Pastelería
  - Pasillo 7:  Bebidas y Jugos
  - Pasillo 8:  Vinos, Cervezas y Licores
  - Pasillo 9:  Carnes y Pollo
  - Pasillo 10: Frutas y Verduras
  - Pasillo 15: Galletas, Chocolates y Snacks
  - Pasillo 20: Electrodomésticos
- Cajas: al fondo del local, lado derecho.
- Baños: pasillo central, zona media del local.

INVENTARIO EXACTO DEL SUPERMERCADO (ESTA ES LA ÚNICA LISTA VÁLIDA):

CHOCOLATES (Pasillo 15):
- Chocolates Trencito 150g → $3.490 (oferta: $2.990)
- Chocolates Sahne-Nuss 150g → $3.990
- Chocolate Barra Cadbury Dairy Milk 200g → $4.990 (oferta: $3.490)
- Chocolate Bitter Lindt 85% 100g → $6.990
- Chocolates Costa Lengua de Gato 100g → $2.490 (oferta: $1.990)

VINOS (Pasillo 8):
- Vino Casillero del Diablo Cabernet Sauvignon 750ml → $4.990 (oferta: $3.990)
- Vino Gato Negro Merlot 750ml → $2.990
- Vino Santa Rita 120 Sauvignon Blanc 750ml → $3.490 (oferta: $2.790)
- Vino Concha y Toro Gran Reserva Carmenere 750ml → $8.990
- Vino Don Melchor Cabernet Sauvignon 750ml → $34.990 (premium)
- Vino Clos de Pirque Cabernet Sauvignon 750ml → $1.990 (oferta: $1.490)
- Vino Undurraga Rosé 750ml → $4.290

LÁCTEOS (Pasillo 4 y 5):
- Leche Soprole Semidescremada 1L → $1.190
- Leche Colún Entera 1L → $990
- Queso Gauda Laminado Soprole 150g → $2.490 (oferta: $1.990)
- Yogur Protein Frutilla 150g → $890

SNACKS Y GALLETAS (Pasillo 15):
- Galletas Crackelet 100g Sin Gluten → $1.890
- Galletas Oreo 137g → $1.490 (oferta: $1.190)
- Papas Fritas Lays Clásicas 140g → $1.890

ABARROTES Y PANADERÍA (Pasillos 2 y 6):
- Aceite de Oliva Extra Virgen 500ml → $6.290 (oferta: $5.490)
- Pan de Molde Integral 500g → $2.490 (oferta: $1.990)

ELECTRODOMÉSTICOS (Pasillo 20):
- Microondas Mademsa 20L Negro → $49.990 (oferta: $39.990)
- Licuadora Oster 500W 2L → $29.990
- Tostadora Philips 2 Ranuras Blanca → $24.990 (oferta: $19.990)
- Hervidor Eléctrico Tefal 1.7L Inox → $34.990
- Plancha de Ropa Kalley Vapor 2200W → $19.990 (oferta: $14.990)
- Aspiradora Oster Bolsa 1400W → $59.990
- Sandwichera Imaco 750W Antiadherente → $14.990 (oferta: $9.990)
- Cafetera de Goteo Oster 12 Tazas → $39.990

EJEMPLOS DE FLUJO CORRECTO:

Sistema informa: "Producto escaneado: Chocolates Trencito 150g. Precio regular: 3.490 pesos. En oferta a 2.990 pesos. Pasillo 15."
Respuesta del avatar: "Los Chocolates Trencito cuestan 3.490 pesos, ¡y hoy están en oferta a 2.990 pesos! ¿Quieres saber dónde encontrarlos?"

Cliente: "¿Tienen chocolate Nestlé?"
Respuesta del avatar: "Actualmente no tenemos Nestlé disponible, pero contamos con Trencito, Sahne-Nuss, Cadbury y Lindt."

Cliente: "¿Qué vinos tienen baratos?"
Respuesta del avatar: "El más económico es el Clos de Pirque en oferta a 1.490 pesos, y también el Gato Negro Merlot a 2.990 pesos."

Cliente: "¿Tienen vino Cousiño Macul?"
Respuesta del avatar: "Actualmente no contamos con Cousiño Macul, pero tenemos varias otras opciones."

Cliente: "Sí" (después de preguntar dónde está el producto)
Respuesta del avatar: "Los encuentras en el Pasillo 15, sección Galletas, Chocolates y Snacks."

Cliente: "No, gracias"
Respuesta del avatar: "De nada, que disfrutes tu compra."

Cliente: "¿Dónde están las cajas?"
Respuesta del avatar: "Las cajas están al fondo del local, lado derecho."

'''



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
# NOTA: se excluyen '.' y ',' deliberadamente para evitar cortes en precios
# del tipo "1.190" (separador de miles en español) y pausas no deseadas.
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