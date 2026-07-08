###############################################################################
#  LLM integration — Ollama (Qwen)
#  Endpoint: http://200.29.189.27:65535/api/chat
###############################################################################

import time
import requests
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from avatars.base_avatar import BaseAvatar
from utils.logger import logger

# ─── Configuración del LLM ────────────────────────────────────────────────────
OLLAMA_URL   = "http://200.29.189.27:65535/api/chat"
OLLAMA_MODEL = "qwen3-vl:32b-instruct"

SYSTEM_PROMPT = '''
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
- No respondas la base de productos completa, solo la que necesites para responder la pregunta del cliente.

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


def llm_response(message: str, avatar_session: "BaseAvatar", datainfo: dict = {}):
    """
    Envía `message` al LLM y alimenta al avatar con los fragmentos de respuesta
    a medida que van llegando (chunking por puntuación).
    """
    try:
        start = time.perf_counter()
        logger.info(f"[LLM] Enviando mensaje: {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": message},
            ],
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