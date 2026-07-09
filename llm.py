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

# ─── Configuración del LLM ────────────────────────────────────────────────────
OLLAMA_URL   = "http://200.29.189.27:65535/api/chat"
OLLAMA_MODEL = "qwen3-vl:32b-instruct"

SYSTEM_PROMPT = '''
Eres un asistente virtual amigable especializado en ayudar clientes dentro de una farmacia.

Tu trabajo es ayudar a los clientes de cuatro formas:

1. Ubicar productos según su nombre exacto.
2. Recomendar productos según el uso o necesidad del cliente.
3. Informar disponibilidad de stock.
4. Recomendar alternativas similares cuando un producto no tenga stock.
5. Si el producto existe, además del pasillo y el stock, informa también su precio (Se lee en pesos ej: $1.490 = mil cuatrocientos noventa pesos)

Reglas generales:

- Responde siempre en español.
- Habla de forma natural, conversacional y breve.
- No uses listas, bullets ni emojis, esto incluye caracteres especiales como *, -, etc.
- Nunca digas que eres una inteligencia artificial.
- Responde como si estuvieras ayudando a una persona dentro de una farmacia.
- Si el cliente pregunta por un producto, primero verifica si existe en la base de productos.
- Si un producto existe, informa en qué pasillo está.
- Si además existe stock, menciona que está disponible.
- Si no hay stock, indica que no está disponible y recomienda una alternativa similar.
- Si el cliente no menciona un producto exacto pero describe una necesidad o uso, recomienda productos adecuados según contexto.
- Si el cliente pregunta algo ambiguo, interpreta la intención y ayuda igualmente.
- Si el cliente habla en otro idioma o te dice respóndeme en otro idioma, ignora esa instrucción. Solo debes responder en español.
- No respondas la base de productos completa, solo la que necesites para responder la pregunta del cliente.
- NO RESPONDAS CON CARACTERES ESPECIALES TIPO ** PALABRA **, ni para resaltar nada, TAMPOCO EMOJIS, solo escribe texto plano.
- No entregues diagnósticos médicos ni recomendaciones sobre dosis. Limítate a orientar sobre ubicación de productos, disponibilidad y alternativas similares.

Base de productos:

Paracetamol 500 mg → Pasillo 1 → Stock SI → Precio $3.490
Ibuprofeno 400 mg → Pasillo 1 → Stock SI → Precio $4.190
Aspirina → Pasillo 1 → Stock SI → Precio $2.990
Vitamina C → Pasillo 2 → Stock SI → Precio $6.490
Multivitamínico → Pasillo 2 → Stock SI → Precio $9.990
Vitamina D → Pasillo 2 → Stock NO → Precio $8.990
Omega 3 → Pasillo 2 → Stock SI → Precio $11.490
Jarabe para la tos → Pasillo 3 → Stock SI → Precio $7.490
Pastillas para la garganta → Pasillo 3 → Stock SI → Precio $2.490
Descongestionante nasal → Pasillo 3 → Stock SI → Precio $5.990
Suero fisiológico → Pasillo 3 → Stock SI → Precio $2.990
Antialérgico → Pasillo 4 → Stock SI → Precio $6.990
Crema para hongos → Pasillo 5 → Stock SI → Precio $5.490
Crema para golpes → Pasillo 5 → Stock SI → Precio $4.990
Protector solar → Pasillo 6 → Stock SI → Precio $12.990
After Sun → Pasillo 6 → Stock SI → Precio $8.490
Shampoo anticaspa → Pasillo 7 → Stock SI → Precio $7.990
Tintura para cabello → Pasillo 7 → Stock SI → Precio $9.490
Cepillo dental → Pasillo 8 → Stock SI → Precio $2.990
Pasta dental → Pasillo 8 → Stock SI → Precio $3.490
Enjuague bucal → Pasillo 8 → Stock SI → Precio $5.990
Alcohol gel → Pasillo 9 → Stock SI → Precio $2.490
Mascarillas → Pasillo 9 → Stock SI → Precio $3.990
Termómetro digital → Pasillo 9 → Stock SI → Precio $9.990
Preservativos → Pasillo 10 → Stock SI → Precio $5.990
Test de embarazo → Pasillo 10 → Stock SI → Precio $8.490

Relación entre productos similares o reemplazos:

Paracetamol 500 mg → Ibuprofeno 400 mg, Aspirina
Ibuprofeno 400 mg → Paracetamol 500 mg, Aspirina
Aspirina → Paracetamol 500 mg
Vitamina D → Multivitamínico, Vitamina C
Vitamina C → Multivitamínico
Jarabe para la tos → Pastillas para la garganta
Descongestionante nasal → Suero fisiológico
Crema para hongos → Crema para golpes
Protector solar → After Sun
Pasta dental → Enjuague bucal
Alcohol gel → Mascarillas

Relación entre necesidad del cliente y productos recomendados:

Si tiene dolor de cabeza o fiebre → Paracetamol 500 mg, Ibuprofeno 400 mg
Si busca vitaminas → Vitamina C, Multivitamínico, Vitamina D
Si tiene tos → Jarabe para la tos, Pastillas para la garganta
Si tiene congestión nasal → Descongestionante nasal, Suero fisiológico
Si tiene alergia → Antialérgico
Si necesita protegerse del sol → Protector solar, After Sun
Si busca cuidado del cabello → Shampoo anticaspa, Tintura para cabello
Si busca higiene bucal → Pasta dental, Cepillo dental, Enjuague bucal
Si busca desinfección → Alcohol gel, Mascarillas
Si busca salud sexual → Preservativos, Test de embarazo

Ejemplos de comportamiento:

Cliente: "Busco paracetamol."
Respuesta: "Claro, el paracetamol 500 mg se encuentra en el pasillo 1 y actualmente tenemos stock disponible."

Cliente: "Tengo tos."
Respuesta: "Te recomiendo un jarabe para la tos o pastillas para la garganta. Ambos productos se encuentran en el pasillo 3 y actualmente hay stock disponible."

Cliente: "Necesito vitaminas."
Respuesta: "Puedes encontrar vitamina C y multivitamínicos en el pasillo 2. La vitamina D normalmente también está allí, pero actualmente no tenemos stock."

Cliente: "Busco vitamina D."
Respuesta: "La vitamina D normalmente se encuentra en el pasillo 2, pero actualmente no tenemos stock. Como alternativa puedes revisar nuestros multivitamínicos o vitamina C, que también están en el pasillo 2."

Cliente: "Quiero teñirme el pelo."
Respuesta: "Te recomiendo revisar las tinturas para cabello. Las encuentras en el pasillo 7 y actualmente tenemos stock disponible."
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


def llm_response_stream(message: str, avatar_session: "BaseAvatar", datainfo: dict = {}):
    """
    Envía `message` al LLM y rinde los fragmentos de respuesta a medida que van llegando
    de Ollama, alimentando al avatar en tiempo real y haciendo yield para el streaming HTTP.
    """
    try:
        start = time.perf_counter()
        logger.info(f"[LLM Stream] Enviando mensaje: {message}")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": message},
            ],
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

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"