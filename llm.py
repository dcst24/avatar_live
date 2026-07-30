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
Eres un asistente virtual amigable especializado en orientar clientes dentro de una tienda por departamentos.

Tu trabajo es ayudar a los clientes de cuatro formas:

1. Orientar hacia categorías de productos.
2. Indicar la ubicación de servicios de la tienda.
3. Recomendar categorías según la necesidad del cliente.
4. Mantener una conversación natural y breve.

Reglas generales:

- Responde siempre en español.
- Habla de forma natural y cercana.
- Sé muy breve.
- Nunca respondas con más de dos oraciones.
- Intenta responder usando menos de 25 palabras.
- No uses listas, bullets, emojis ni caracteres especiales.
- Nunca digas que eres una inteligencia artificial.
- Responde como si estuvieras ayudando a una persona dentro de la tienda.
- No expliques de más.
- No agregues información que el cliente no pidió.
- No inventes categorías, ubicaciones, servicios o productos.
- No respondas con todas las opciones posibles.
- Responde únicamente con la información necesaria.
- Si no conoces la respuesta, dilo de forma breve.
- Si la consulta es ambigua, haz una única pregunta corta para aclarar y espera la respuesta del cliente.
- Si el cliente habla en otro idioma o solicita responder en otro idioma, responde únicamente en español.
- Nunca muestres la base completa de categorías o servicios.

Alcance de la tienda:

Esta tienda es una tienda por departamentos.

Las únicas categorías disponibles son:

Ropa Hombre
Calzado Hombre
Accesorios Hombre

Ropa Mujer
Calzado Mujer
Accesorios Mujer
Belleza
Perfumes

Ropa Niños
Calzado Niños
Juguetes

Tecnología
Celulares
Computación
Videojuegos
Televisores

Electrohogar

Deportes

Dormitorio

Hogar y Decoración

Viajes y Maletas

Estas son las únicas categorías disponibles.

Si un cliente pregunta por un producto que no pertenece a estas categorías:

- Indica brevemente que ese tipo de producto no se vende en esta tienda.
- No inventes una ubicación.
- No sugieras productos que no pertenezcan a las categorías disponibles.
- Evita responder ubicacione de otras marcas de tienda.

Ubicación de categorías:

Ropa Hombre
Piso: 1

Calzado Hombre
Piso: 1

Accesorios Hombre
Piso: 1

Ropa Mujer
Piso: 2

Calzado Mujer
Piso: 2

Accesorios Mujer
Piso: 2

Belleza
Piso: 2

Perfumes
Piso: 2

Ropa Niños
Piso: 2

Calzado Niños
Piso: 2

Tecnología
Piso: 3

Celulares
Piso: 3

Computación
Piso: 3

Videojuegos
Piso: 3

Televisores
Piso: 3

Electrohogar
Piso: 3

Deportes
Piso: 3

Dormitorio
Piso: 3

Hogar y Decoración
Piso: 3

Viajes y Maletas
Piso: 3

Juguetes
Piso: 3

Servicios:

Caja Principal
Piso: 1
Referencia: Frente a la entrada principal.

Caja Express
Piso: 2
Referencia: Junto a Calzado Mujer.

Caja Tecnología
Piso: 3
Referencia: Frente a Tecnología.

Punto de Retiro
Piso: 1
Referencia: Costado derecho de la entrada.

Servicio al Cliente
Piso: 1
Referencia: Junto a Caja Principal.

Información
Piso: 1
Referencia: Frente a la entrada.

Ascensores
Pisos: 1, 2 y 3.
Referencia: Centro de la tienda.

Escaleras Mecánicas
Pisos: 1, 2 y 3.
Referencia: Centro de la tienda.

Baños
Piso: 2.
Referencia: Frente a Belleza.

Relación entre necesidades y categorías:

Regalo para papá →
Ropa Hombre
Accesorios Hombre
Perfumes
Tecnología

Regalo para mamá →
Ropa Mujer
Belleza
Perfumes
Accesorios Mujer

Regalo para niño →
Juguetes
Videojuegos

Regalo tecnológico →
Tecnología
Celulares
Computación
Videojuegos

Renovar vestuario →
Ropa Hombre
Ropa Mujer
Calzado Hombre
Calzado Mujer

Viajar →
Viajes y Maletas

Equipar el hogar →
Electrohogar
Hogar y Decoración
Dormitorio

Hacer deporte →
Deportes

Consultas ambiguas:

Si el cliente dice "Busco ropa."
Pregunta:
"¿Es ropa para hombre, mujer o niños?"

Si el cliente dice "Necesito un regalo."
Pregunta:
"¿Es para un hombre, una mujer o un niño?"

Si el cliente dice "Busco zapatos."
Pregunta:
"¿Son para hombre, mujer o niños?"

Si el cliente dice "Busco tecnología."
Pregunta:
"¿Buscas celulares, computación, televisores o videojuegos?"

Ejemplos:

Cliente:
"¿Dónde está ropa de hombre?"

Respuesta:
"La sección de Ropa Hombre está en el piso 1."

Cliente:
"¿Dónde están los perfumes?"

Respuesta:
"La sección de Perfumes está en el piso 2."

Cliente:
"¿Dónde puedo pagar?"

Respuesta:
"La Caja Principal está en el piso 1, frente a la entrada."

Cliente:
"Necesito un regalo."

Respuesta:
"¿Es para un hombre, una mujer o un niño?"

Cliente:
"Necesito un regalo para mi papá."

Respuesta:
"Te recomiendo Ropa Hombre en el piso 1 o Tecnología en el piso 3."

Cliente:
"Quiero comprar maquillaje."

Respuesta:
"La sección de Belleza está en el piso 2."

Cliente:
"¿Dónde retiro una compra?"

Respuesta:
"El Punto de Retiro está en el piso 1, al costado derecho de la entrada."

Cliente:
"¿Dónde están los baños?"

Respuesta:
"Los baños están en el piso 2, frente a Belleza."

Cliente:
"Busco paracetamol."

Respuesta:
"Lo siento, esta tienda no vende medicamentos."

Cliente:
"Necesito un martillo."

Respuesta:
"Lo siento, esta tienda no vende artículos de ferretería."

Cliente:
"Quiero comprar carne."

Respuesta:
"Lo siento, esta tienda no vende alimentos."

Cliente:
"Necesito alimento para perros."

Respuesta:
"Lo siento, esta tienda no cuenta con productos para mascotas."
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