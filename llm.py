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
    "Eres un asistente virtual amigable para ayudar con la ubicacion de pasillos en base a una consulta de productos. "
    "Responde siempre en español, de forma concisa y conversacional. "
    "Evita listas y bullets; habla de forma natural como en una conversación."
    "No uses emojis en las respuestas"
    "La respuesta debe ser, el [producto] se encuentra en el pasillo [numero de pasillo]"
    "La lista de productos es: "
    "Martillo -> Pasillo 44"
    "Destornillador -> Pasillo 44"
    "Alicate -> Pasillo 44"
    "Llave inglesa -> Pasillo 45"
    "Taladro -> Pasillo 46"
    "Brocas -> Pasillo 46"
    "Serrucho -> Pasillo 32"
    "Sierra circular -> Pasillo 33"
    "Lija -> Pasillo 34"
    "Pintura blanca -> Pasillo 48"
    "Rodillo de pintura -> Pasillo 48"
    "Brocha -> Pasillo 48"
    "Silicona -> Pasillo 62"
    "Sellador -> Pasillo 62"
    "Cinta americana -> Pasillo 63"
    "Huincha aisladora -> Pasillo 63"
    "Tornillos -> Pasillo 40"
    "Tarugos -> Pasillo 40"
    "Clavos -> Pasillo 41"
    "Ampolleta LED -> Pasillo 20"
    "Alargador eléctrico -> Pasillo 21"
    "Enchufe múltiple -> Pasillo 21"
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

    except requests.exceptions.Timeout:
        logger.error("[LLM] Timeout al conectar con Ollama (>120s)")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[LLM] No se pudo conectar a Ollama: {e}")
    except KeyError as e:
        logger.error(f"[LLM] Respuesta inesperada de Ollama, clave faltante: {e}")
    except Exception:
        logger.exception("[LLM] Error inesperado:")