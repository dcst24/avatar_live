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

# ─── Carga dinámica de base de datos Servipag (Pago de Cuentas) ─────────────
_SERVIPAG_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "servipag_bdd.json")
_RETAIL_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "bdd.json")
_BDD_PATH = _SERVIPAG_BDD_PATH if os.path.exists(_SERVIPAG_BDD_PATH) else _RETAIL_BDD_PATH

_BDD: dict = {}
_CATEGORIAS_SERVICIOS: list = []
_CATEGORIAS_BY_ID: dict = {}
_EMPRESAS_BY_ID: dict = {}
_EMPRESAS_BY_ALIAS: dict = {}
_CUENTAS: list = []
_CUENTAS_BY_CLEAN_RUT: dict = {}
_CUENTAS_BY_IDENTIFICADOR: dict = {}
_CUENTAS_BY_EMPRESA: dict = {}

def clean_rut(rut_str: str) -> str:
    """Limpia el RUT removiendo puntos, guiones y espacios, dejando dígitos y K mayúscula."""
    if not rut_str:
        return ""
    return re.sub(r'[^0-9kK]', '', rut_str).upper()

def _format_account_for_prompt(acc: dict) -> str:
    monto_fmt = f"${acc['monto']:,} pesos".replace(",", ".") if acc.get('monto', 0) > 0 else "0 pesos"
    venc_txt = f"Vence: {acc['fecha_vencimiento']}" if acc.get('fecha_vencimiento') else "Sin fecha de vencimiento"
    return (
        f"- Empresa: {acc.get('empresa_nombre', '')} | Servicio: {acc.get('categoria', '')} | "
        f"Titular: {acc.get('nombre_titular', '')} (RUT: {acc.get('rut_titular', '')}) | "
        f"{acc.get('identificador_tipo', 'Identificador')}: {acc.get('identificador', '')} | "
        f"Monto: {monto_fmt} | Estado: {acc.get('estado', '').upper()} ({acc.get('detalle_estado', '')}) | {venc_txt}"
    )

def _format_category_for_prompt(cat: dict) -> str:
    empresas_str = ", ".join([e["nombre"] for e in cat.get("empresas", [])])
    return f"- Servicio {cat['nombre']}: Empresas disponibles: {empresas_str}"


BASE_SYSTEM_PROMPT = '''Eres el Asistente Virtual de Servipag en un tótem interactivo de atención y pago de cuentas en Chile.
Tu función principal es guiar y orientar al usuario de forma clara, ágil, empática y profesional para consultar el estado de sus cuentas (luz, agua, internet, gas, autopistas/TAG) y proceder a su pago.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones cortas, no más de 15 a 20 palabras en total).
- El usuario te escucha hablar mediante síntesis de voz en un tótem interactivo. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones, saludos largos ni rodeos.
- NUNCA uses formato Markdown como asteriscos (*), negritas (**), guiones (- o —), flechas (→) ni viñetas (•).
- Lee siempre los montos en pesos chilenos completos (ej: "28.990 pesos").

FLUJO CONVERSACIONAL PASO A PASO:
1. IDENTIFICAR SERVICIO:
   Si el usuario saluda o dice que quiere pagar una cuenta sin especificar cuál, pregúntale:
   "¡Hola! ¿Qué cuenta deseas pagar hoy: luz, agua, internet, gas o autopista?"
2. IDENTIFICAR EMPRESA:
   Si ya se conoce el tipo de servicio pero no la empresa, pregúntale cuál es su empresa proveedora mencionando las principales:
   Ejemplo (Luz): "¿De qué empresa es tu cuenta de luz: Enel, CGE o Chilquinta?"
   Ejemplo (Agua): "¿De qué empresa es tu cuenta de agua: Aguas Andinas, Essbio o Esval?"
   Ejemplo (Internet): "¿De qué compañía es tu servicio: VTR, Movistar, Entel o Mundo?"
3. IDENTIFICAR CUENTA O RUT:
   Si ya se conoce la empresa pero falta el identificador, solicítalo con amabilidad:
   Ejemplo: "¿Me indicas tu número de cliente o tu RUT?"
4. INFORMAR ESTADO Y MONTO (DISTINGUIR CON EXACTITUD LOS 4 CASOS):
   - DEUDA ACTIVA (al día / próxima a vencer):
     Informa el monto y fecha de vencimiento, y pregunta si desea pagar.
     Ejemplo: "Tu cuenta de Enel es de 28.990 pesos con vencimiento el 15 de septiembre. ¿Deseas pagarla ahora?"
   - DEUDA VENCIDA (atrasada / corte programado):
     Informa con claridad el monto vencido y una advertencia amable.
     Ejemplo: "Tu cuenta de VTR tiene una deuda vencida de 38.990 pesos con aviso de corte. ¿Deseas pagarla ahora?"
   - DEUDA PAGADA / AL DÍA:
     Informa que la cuenta no tiene saldo pendiente (cero pesos) y pregunta si desea pagar otra cuenta.
     Ejemplo: "Tu cuenta de Enel se encuentra totalmente al día con cero pesos pendientes. ¿Deseas pagar otra cuenta?"
   - AÚN NO HAY DEUDAS / SIN FACTURACIÓN:
     Informa que la cuenta no registra facturación pendiente por el momento.
     Ejemplo: "Tu cuenta de Metrogas no registra facturación emitida por ahora. ¿Te ayudo con otra cuenta?"
5. CONFIRMACIÓN Y TRANSICIÓN DE PAGO:
   Si el usuario responde afirmativamente que desea pagar ("sí", "pagar", "quiero pagar", "proceder", "claro"):
   Responde EXACTAMENTE con la instrucción de pago en el lector de tarjeta:
   "Entendido, serás redirigido a la plataforma de pago. Por favor acerca o inserta tu tarjeta en el lector."

CONSULTA DIRECTA POR RUT:
- Si el usuario proporciona directamente su RUT (ej: "18.765.432-1"):
  Consulta sus cuentas asociadas y dale un resumen conciso indicando las que tienen deuda activa o vencida.
  Ejemplo: "Hola Juan, tienes dos cuentas pendientes: Enel por 28.990 pesos y Aguas Andinas por 14.500 pesos. ¿Cuál deseas pagar?"

REGLA ABSOLUTA DE TEMÁTICA:
- Solo atiendes consultas sobre Servipag, empresas proveedoras y pago de servicios básicos en Chile.
- No respondas preguntas de programación, cultura general o temas ajenos. Responde cortésmente: "Disculpa, solo atiendo consultas y pagos de cuentas en Servipag. ¿Qué cuenta deseas pagar hoy?"

EJEMPLOS DE FLUJO CORRECTO (CORTOS Y PRECISOS):

Cliente: "Hola, quiero pagar una cuenta"
Respuesta del avatar: "¡Hola! ¿Qué cuenta deseas pagar: luz, agua, internet, gas o autopista?"

Cliente: "La luz"
Respuesta del avatar: "¿De qué empresa es tu cuenta: Enel, CGE o Chilquinta?"

Cliente: "Enel, cliente 1234567"
Respuesta del avatar: "Tu cuenta de Enel tiene un saldo de 28.990 pesos al día. ¿Deseas pagarla ahora?"

Cliente: "Sí, pagar"
Respuesta del avatar: "Entendido, serás redirigido a la plataforma de pago. Por favor acerca o inserta tu tarjeta en el lector."

Cliente: "No, gracias"
Respuesta del avatar: "Perfecto, si necesitas algo más aquí estaré. ¡Que tengas un excelente día!"

Cliente: "Mi RUT es 15.432.987-K"
Respuesta del avatar: "Hola María, tu cuenta de VTR tiene una deuda vencida de 38.990 pesos. ¿Deseas pagarla ahora?"

Cliente: "Quiero revisar mi cuenta de Enel, RUT 12.345.678-5"
Respuesta del avatar: "Tu cuenta de Enel se encuentra al día con cero pesos pendientes. ¿Deseas pagar otra cuenta?"

Cliente: "Metrogas, cliente 65432109"
Respuesta del avatar: "Tu cuenta de Metrogas no registra facturación pendiente por el momento. ¿Deseas consultar otro servicio?"

Cliente: "Costanera Norte, patente BBCL12"
Respuesta del avatar: "Tu cuenta de Costanera Norte tiene una deuda vencida de 45.200 pesos. ¿Deseas proceder al pago?"
'''

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Selecciona e inyecta dinámicamente las cuentas, empresas y categorías
    relevantes para la consulta actual del usuario en Servipag.
    """
    search_text = user_msg.lower()
    for h in history[-2:]:
        search_text += " " + h.get("content", "").lower()

    # Si estamos en modo Servipag
    if _CUENTAS or _CATEGORIAS_SERVICIOS:
        matched_accounts = []
        matched_categories = []
        matched_companies = []

        # 1. Búsqueda por RUT (con formato o solo números)
        clean_user_ruts = re.findall(r'\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]\b|\b\d{7,8}[\dkK]\b', search_text)
        for r in clean_user_ruts:
            cr = clean_rut(r)
            if cr in _CUENTAS_BY_CLEAN_RUT:
                for acc in _CUENTAS_BY_CLEAN_RUT[cr]:
                    if acc not in matched_accounts:
                        matched_accounts.append(acc)

        # 2. Búsqueda por identificador de cliente / patente
        for ident, acc in _CUENTAS_BY_IDENTIFICADOR.items():
            if ident.lower() in search_text:
                if acc not in matched_accounts:
                    matched_accounts.append(acc)

        # 3. Búsqueda por alias / nombre de empresa
        for alias, emp in _EMPRESAS_BY_ALIAS.items():
            if f" {alias} " in f" {search_text} ":
                if emp not in matched_companies:
                    matched_companies.append(emp)
                emp_id = emp.get("id", "")
                if emp_id in _CUENTAS_BY_EMPRESA:
                    for acc in _CUENTAS_BY_EMPRESA[emp_id]:
                        if acc not in matched_accounts:
                            matched_accounts.append(acc)

        # 4. Búsqueda por categoría de servicio
        for cat in _CATEGORIAS_SERVICIOS:
            cat_id = cat.get("id", "")
            sinonimos = cat.get("sinonimos", []) + [cat_id, cat.get("nombre", "").lower()]
            if any(s in search_text for s in sinonimos):
                if cat not in matched_categories:
                    matched_categories.append(cat)

        extra_parts = []
        if matched_accounts:
            extra_parts.append("CUENTAS ENCONTRADAS PARA ESTE CLIENTE:\n" + "\n".join([_format_account_for_prompt(a) for a in matched_accounts]))
        if matched_companies:
            comp_info = [f"- {c['nombre']} (Identificador: {c['tipo_identificador']}, formato: {c.get('formato_identificador','')})" for c in matched_companies]
            extra_parts.append("EMPRESAS SELECCIONADAS:\n" + "\n".join(comp_info))
        if matched_categories and not matched_accounts:
            extra_parts.append("SERVICIOS Y EMPRESAS DISPONIBLES:\n" + "\n".join([_format_category_for_prompt(c) for c in matched_categories]))

        if extra_parts:
            return f"{BASE_SYSTEM_PROMPT}\n\nCONTEXTO ESPECÍFICO DE ESTA CONSULTA:\n" + "\n\n".join(extra_parts)
        return BASE_SYSTEM_PROMPT

    return BASE_SYSTEM_PROMPT


def reload_catalog() -> None:
    global _BDD, _CATEGORIAS_SERVICIOS, _CATEGORIAS_BY_ID, _EMPRESAS_BY_ID, _EMPRESAS_BY_ALIAS
    global _CUENTAS, _CUENTAS_BY_CLEAN_RUT, _CUENTAS_BY_IDENTIFICADOR, _CUENTAS_BY_EMPRESA

    _BDD = {}
    _CATEGORIAS_SERVICIOS = []
    _CATEGORIAS_BY_ID = {}
    _EMPRESAS_BY_ID = {}
    _EMPRESAS_BY_ALIAS = {}
    _CUENTAS = []
    _CUENTAS_BY_CLEAN_RUT = {}
    _CUENTAS_BY_IDENTIFICADOR = {}
    _CUENTAS_BY_EMPRESA = {}

    try:
        with open(_BDD_PATH, encoding="utf-8") as _f:
            _BDD = json.load(_f)

        # Si es base de datos Servipag
        if "categorias_servicios" in _BDD or "cuentas_clientes" in _BDD:
            _CATEGORIAS_SERVICIOS = _BDD.get("categorias_servicios", [])
            _CATEGORIAS_BY_ID = {c["id"]: c for c in _CATEGORIAS_SERVICIOS}

            for cat in _CATEGORIAS_SERVICIOS:
                for emp in cat.get("empresas", []):
                    emp["categoria"] = cat["id"]
                    _EMPRESAS_BY_ID[emp["id"]] = emp
                    _EMPRESAS_BY_ALIAS[emp["nombre"].lower()] = emp
                    _EMPRESAS_BY_ALIAS[emp["id"].lower()] = emp
                    for al in emp.get("alias", []):
                        _EMPRESAS_BY_ALIAS[al.lower()] = emp

            _CUENTAS = _BDD.get("cuentas_clientes", [])
            for acc in _CUENTAS:
                cr = clean_rut(acc.get("rut_titular", ""))
                if cr:
                    _CUENTAS_BY_CLEAN_RUT.setdefault(cr, []).append(acc)

                ident = str(acc.get("identificador", "")).strip()
                if ident:
                    _CUENTAS_BY_IDENTIFICADOR[ident] = acc

                emp_id = acc.get("empresa_id", "")
                if emp_id:
                    _CUENTAS_BY_EMPRESA.setdefault(emp_id, []).append(acc)

            logger.info(
                f"[LLM] Base de datos Servipag cargada desde {_BDD_PATH}: "
                f"{len(_CATEGORIAS_SERVICIOS)} categorías, {len(_EMPRESAS_BY_ID)} empresas, "
                f"{len(_CUENTAS)} cuentas registradas ({len(_CUENTAS_BY_CLEAN_RUT)} RUTs)"
            )
        else:
            logger.warning(f"[LLM] Formato de BDD no reconocido en {_BDD_PATH}")

    except Exception as _e:
        logger.error(f"[LLM] Error cargando base de datos: {_e}")

reload_catalog()




# ─── Detección inteligente de oraciones para streaming de voz ultra-rápido ───
MIN_CHUNK_LEN = 120  # caracteres mínimos antes de enviar un fragmento (evita cortes y desincronización en respuestas cortas)

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

                # Rinde el token de inmediato para la interfaz de chat en tiempo real
                yield content

                # Dividir para el TTS del avatar solo si el buffer es suficientemente largo (>= 120 chars)
                # y alcanza un límite de oración natural, evitando micro-cortes a mitad de respuestas cortas
                if len(chunk_buf) >= MIN_CHUNK_LEN and _is_sentence_boundary(chunk_buf):
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
                logger.info(f"[LLM Stream] -> avatar (final): {last_frag}")
                avatar_session.put_msg_txt(last_frag, datainfo)

        # Guardar turno completo en historial (normalizado)
        _append_to_history(sessionid, message, normalizar(full_text))

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"