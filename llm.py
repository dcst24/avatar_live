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

    # 5. Eliminar viñetas y bullets de lista
    # Solo guiones que son viñetas: al inicio de línea seguidos de espacio, o rodeados de espacios
    text = re.sub(r'(?m)^\s*[—–]\s+', ' ', text)   # em-dash/en-dash al inicio (siempre viñeta)
    text = re.sub(r'(?m)^\s*-\s+', ' ', text)       # guion corto al inicio de línea como viñeta
    text = re.sub(r'\s[-—–]\s', ' ', text)           # guion/em-dash entre espacios (viñeta inline)
    text = re.sub(r'[*#|_\\/\[\]{}~^<>•·●○■◆▪]', ' ', text)

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

    # 8. Convertir RUT / Rut a minúsculas 'rut' para que los motores TTS lo pronuncien como palabra y no como sigla ('erre u te')
    text = re.sub(r'\b[Rr][Uu][Tt]\b', 'rut', text)

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


_SPANISH_NUMS = {
    'cero': 0, 'un': 1, 'uno': 1, 'una': 1,
    'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
    'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9,
    'diez': 10, 'once': 11, 'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15,
    'dieciseis': 16, 'dieciséis': 16, 'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19,
    'veinte': 20, 'veintiuno': 21, 'veintidos': 22, 'veintidós': 22, 'veintitres': 23, 'veintitrés': 23,
    'veinticuatro': 24, 'veinticinco': 25, 'veintiseis': 26, 'veintiséis': 26, 'veintisiete': 27,
    'veintiocho': 28, 'veintinueve': 29,
    'treinta': 30, 'cuarenta': 40, 'cincuenta': 50,
    'sesenta': 60, 'setenta': 70, 'ochenta': 80, 'noventa': 90,
    'cien': 100, 'ciento': 100, 'doscientos': 200, 'trescientos': 300,
    'cuatrocientos': 400, 'quinientos': 500, 'seiscientos': 600,
    'setecientos': 700, 'ochocientos': 800, 'novecientos': 900
}

def _parse_spoken_spanish_numbers(text: str) -> str:
    """
    Convierte números hablados en español a dígitos (ej: 'doce tres cuatro cinco...' -> '12 3 4 5...').
    Especialmente útil cuando el STT transcribe números en palabras al dictar RUTs.
    """
    if not text:
        return ""
    # Tokeniza preservando palabras, dígitos, guiones y signos de puntuación
    tokens = re.findall(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ]+|\d+|[-]|[,.:;?!¿¡]', text)
    result = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        tok_lower = tok.lower()
        # Centenas compuestas: 'trescientos cuarenta y cinco' -> 345
        if tok_lower in _SPANISH_NUMS and _SPANISH_NUMS[tok_lower] >= 100 and i + 1 < n and tokens[i+1].lower() in _SPANISH_NUMS:
            val = _SPANISH_NUMS[tok_lower]
            i += 1
            if i + 2 < n and tokens[i].lower() in _SPANISH_NUMS and tokens[i+1].lower() == 'y' and tokens[i+2].lower() in _SPANISH_NUMS:
                val += _SPANISH_NUMS[tokens[i].lower()] + _SPANISH_NUMS[tokens[i+2].lower()]
                i += 3
            elif tokens[i].lower() in _SPANISH_NUMS:
                val += _SPANISH_NUMS[tokens[i].lower()]
                i += 1
            result.append(str(val))
        # Decenas compuestas: 'cuarenta y cinco' -> 45
        elif tok_lower in _SPANISH_NUMS and i + 2 < n and tokens[i+1].lower() == 'y' and tokens[i+2].lower() in _SPANISH_NUMS:
            val = _SPANISH_NUMS[tok_lower] + _SPANISH_NUMS[tokens[i+2].lower()]
            result.append(str(val))
            i += 3
        # Número simple en palabras
        elif tok_lower in _SPANISH_NUMS:
            result.append(str(_SPANISH_NUMS[tok_lower]))
            i += 1
        # Dígito verificador K/ka/ca
        elif tok_lower in ('k', 'ka', 'ca') and (i > 0 and (tokens[i-1].lower() in ('guion', 'guión', 'raya', 'menos', '-') or (result and (result[-1].isdigit() or result[-1] == '-')))):
            result.append('K')
            i += 1
        # Separadores de guion
        elif tok_lower in ('guion', 'guión', 'raya', 'menos'):
            result.append('-')
            i += 1
        # Conectores de millones / mil en RUTs dictados
        elif tok_lower in ('millon', 'millones', 'mil') and (result and result[-1].isdigit()):
            i += 1
        elif tok.isdigit() or tok == '-':
            result.append(tok)
            i += 1
        else:
            result.append(tok)
            i += 1

    s = ' '.join(result)
    s = re.sub(r'\s+([,.:;?!])', r'\1', s)
    s = re.sub(r'([¿¡])\s+', r'\1', s)
    # Colapsar puntos y comas entre dígitos (ej: '12. 345. 678' -> '12345678')
    s = re.sub(r'(?<=\d)\s*[\.,]\s*(?=\d)', '', s)
    s = re.sub(r'(?<=\d)\s+(?=[\dkK]\b)', '', s)
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'(?<=\d)\s+(?=\d)', '', s)
    s = re.sub(r'(\d+)-([\dkK])\b', r'\1-\2', s)
    return s


def normalize_user_input(text: str) -> str:
    """
    Normaliza el texto de entrada del usuario para mitigar errores comunes del STT:
    1. Transcripción de 'Enel' como 'en', 'en el', 'en él', 'ener', 'ene'.
    2. Dígitos espaciados de RUTs y números de clientes: '1 2 3 4 5 6 7 8 - 5' -> '12345678-5'.
    3. Palabras de números dictados en español: 'doce tres cuatro...' -> '1234...'.
    4. Palabras de puntuación como 'guion', 'guión', 'raya', 'menos'.
    """
    if not text:
        return ""
    s = text.strip()

    # 1. Normalizar Enel si el STT transcribió 'En', 'en el', 'en él', 'ener', 'ene'
    s = re.sub(r'^(?:en|en\s+el|en\s+él|ene|ener)$', 'Enel', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:empresa|cuenta|para|de)\s+(?:en\s+el|en\s+él|ener|ene|en)\b', lambda m: m.group(0).split()[0] + ' Enel', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:en\s+el|en\s+él|ener|ene)\b', 'Enel', s, flags=re.IGNORECASE)
    s = re.sub(r'\ben\s*,\s*', 'Enel, ', s, flags=re.IGNORECASE)
    s = re.sub(r'\ben\s+(?=rut|cliente|número|numero|\d)', 'Enel ', s, flags=re.IGNORECASE)

    # 2. Parsear números hablados en palabras españolas a dígitos
    s = _parse_spoken_spanish_numbers(s)

    # 3. Colapsar puntos y comas entre dígitos (cuando STT pone pausas tipo '12, 345, 678-5' o '12. 345. 678-5')
    s = re.sub(r'(?<=\d)\s*[\.,]\s*(?=\d)', '', s)

    # 4. Normalizar guion y espacios alrededor
    s = re.sub(r'\s*(?:-|guion|guión|raya|menos)\s*', '-', s, flags=re.IGNORECASE)

    # 5. Colapsar espacios entre dígitos consecutivos (ej: '1 2 3 4 5 6 7 8' -> '12345678')
    s = re.sub(r'(?<=\d)\s+(?=[\dkK]\b)', '', s)
    s = re.sub(r'(?<=\d)\s+(?=\d)', '', s)

    # 6. Asegurar formato RUT con guión: '12345678-5'
    s = re.sub(r'(\d+)-([\dkK])\b', r'\1-\2', s)

    return s


def extract_rut(text: str) -> str:
    """
    Extrae un RUT chileno completo y válido (7 a 8 dígitos + dígito verificador).
    Retorna su forma limpia en mayúsculas (ej: '123456785', '15432987K') o None si no es un RUT válido.
    """
    if not text:
        return None
    norm = normalize_user_input(text)
    # Formato con guión o formato chileno estándar (ej: 12.345.678-5, 12345678-5, 7.123.456-K)
    m = re.search(r'\b(\d{1,2}(?:\.?\d{3}){2})-?([0-9kK])\b|\b(\d{7,8})-?([0-9kK])\b', norm, re.IGNORECASE)
    if m:
        body = m.group(1) or m.group(3)
        dv = m.group(2) or m.group(4)
        return clean_rut(body) + dv.upper()
    # Formato continuo de 8 o 9 caracteres alfanuméricos cuando el mensaje es predominantemente el RUT
    clean = re.sub(r'[^0-9kK]', '', norm).upper()
    if 8 <= len(clean) <= 9 and re.search(r'^\d{7,8}[0-9kK]$', clean):
        return clean
    return None


def extract_incomplete_number(text: str) -> str:
    """
    Detecta si el usuario ingresó o dictó un número incompleto (1 a 5 dígitos),
    que no califica como RUT chileno ni como número de cliente válido.
    """
    if not text:
        return None
    norm = normalize_user_input(text)
    # Si ya contiene un RUT completo, no es número incompleto
    if extract_rut(norm):
        return None
    # Si contiene un identificador de cliente válido (6 a 9 dígitos), no es incompleto
    if re.search(r'\b\d{6,9}\b', norm):
        return None
    # Detectar números aislados de 1 a 5 dígitos
    m = re.search(r'\b\d{1,5}\b', norm)
    if m:
        return m.group(0)
    return None


def extract_identificador(text: str, found_rut: str = None) -> str:
    """
    Extrae un número de cliente de servicios básicos (6 a 9 dígitos numéricos
    que no correspondan al RUT ya identificado).
    """
    if not text:
        return None
    norm = normalize_user_input(text)
    idents = re.findall(r'\b\d{6,9}\b', norm)
    if idents:
        for idt in idents:
            if found_rut and idt in found_rut:
                continue
            return idt
    return None


def extract_user_entities(user_msg: str, history: list = []) -> tuple:
    """
    Extrae entidades de la conversación asegurando que:
    1. Empresa y servicio provengan EXCLUSIVAMENTE de los mensajes del USUARIO
       (evita falsos positivos por preguntas del asistente como '¿De qué empresa: Enel, CGE o Chilquinta?').
    2. Los números incompletos (< 6 dígitos) se aíslen para no buscar cuentas fantasmas.
    3. El RUT del mensaje actual tenga prioridad absoluta sobre RUTs anteriores.
    4. Las consultas de RUTs anteriores no contaminen la empresa o categoría de una nueva consulta.
    Retorna (rut, incomplete_number, identificador, empresa, categoria, intencion_pago).
    """
    norm_current = normalize_user_input(user_msg)
    user_turns = [h.get("content", "") for h in history if h.get("role") == "user"]

    # 1. RUT chileno
    rut = extract_rut(norm_current)
    current_has_rut = bool(rut)
    incomplete_num = extract_incomplete_number(norm_current)

    option_words = {
        '1': 1, 'uno': 1, 'un': 1, 'primera': 1, 'primero': 1,
        '2': 2, 'dos': 2, 'segunda': 2, 'segundo': 2,
        '3': 3, 'tres': 3, 'tercera': 3, 'tercero': 3,
        '4': 4, 'cuatro': 4, 'cuarta': 4, 'cuarto': 4,
        '5': 5, 'cinco': 5, 'quinta': 5, 'quinto': 5,
    }

    ident_in_current = extract_identificador(norm_current, rut)

    # Solo buscar selección de opción (ej: "la 1", "el dos", "opción 2", "primera")
    # si el turno actual NO es un RUT ni un identificador de cliente
    opt_match = None
    if not current_has_rut and not ident_in_current:
        opt_match = re.search(
            r'\b(?:la\s+|el\s+|opci[oó]n\s+|cuenta\s+|n[uú]mero\s+|quiero\s+la\s+|quiero\s+el\s+|pagar\s+la\s+|pagar\s+el\s+)?(1|2|3|4|5|uno|dos|tres|cuatro|cinco|primera|primero|segunda|segundo|tercera|tercero|cuarta|quinta)\b',
            norm_current.lower()
        )

    # Si el usuario dijo una opción numérica (ej: "la 1", "uno", "2") y hay un RUT previo, no es número incompleto
    if opt_match and not rut:
        for t in reversed(user_turns):
            r = extract_rut(t)
            if r:
                rut = r
                incomplete_num = None
                break

    if not rut and not incomplete_num:
        for t in reversed(user_turns):
            r = extract_rut(t)
            if r:
                rut = r
                break

    # 2. Identificador numérico de cliente (6 a 9 dígitos)
    ident = ident_in_current
    if not ident and not incomplete_num:
        for t in reversed(user_turns):
            idt = extract_identificador(t, rut)
            if idt:
                ident = idt
                break

    # Aislamiento de contexto entre consultas de RUTs:
    last_rut_turn_idx = -1
    for idx, t in enumerate(user_turns):
        if extract_rut(t) or extract_identificador(t):
            last_rut_turn_idx = idx

    if rut and last_rut_turn_idx >= 0 and not opt_match:
        relevant_user_turns = user_turns[last_rut_turn_idx + 1:] + [user_msg]
    else:
        relevant_user_turns = user_turns + [user_msg]

    # 3. Empresa y Categoría (buscada prioritariamente en los turnos más recientes del usuario)
    empresa = None
    categoria = None

    if opt_match and rut and not current_has_rut:
        matched_word = opt_match.group(1).lower()
        if matched_word in option_words:
            opt_idx = option_words[matched_word] - 1
            cuentas_rut_lista = _CUENTAS_BY_CLEAN_RUT.get(clean_rut(rut), [])
            if 0 <= opt_idx < len(cuentas_rut_lista):
                target_acc = cuentas_rut_lista[opt_idx]
                empresa = target_acc.get("empresa_id")
                categoria = target_acc.get("categoria")
                incomplete_num = None

    if not empresa:
        for t in reversed(relevant_user_turns):
            norm_t = normalize_user_input(t).lower()
            for alias, emp in sorted(_EMPRESAS_BY_ALIAS.items(), key=lambda x: len(x[0]), reverse=True):
                if re.search(r'\b' + re.escape(alias) + r'\b', norm_t):
                    empresa = emp.get("id")
                    if not categoria:
                        categoria = emp.get("categoria")
                    break
            if empresa:
                break

    if not categoria:
        for t in reversed(relevant_user_turns):
            norm_t = normalize_user_input(t).lower()
            for cat in _CATEGORIAS_SERVICIOS:
                cat_id = cat.get("id", "")
                sinonimos = cat.get("sinonimos", []) + [cat_id, cat.get("nombre", "").lower()]
                if any(re.search(r'\b' + re.escape(s) + r'\b', norm_t) for s in sinonimos):
                    categoria = cat_id
                    break
            if categoria:
                break

    # 5. Intención afirmativa de pago
    intencion_pago = bool(re.search(
        r'\b(si|sí|pagar|quiero pagar|pagar ahora|cancelo|proceder|pagemosla|pagémosla|claro)\b',
        norm_current.lower()
    ))

    return rut, incomplete_num, ident, empresa, categoria, intencion_pago


def extract_entities(user_msg: str, history: list = []) -> tuple:
    """
    Función de compatibilidad: extrae (clean_rut, empresa_id, identificador, categoria_id).
    """
    rut, inc_num, ident, emp, cat, pay = extract_user_entities(user_msg, history)
    return rut, emp, ident, cat


def formatear_fecha_natural(fecha_str: str) -> str:
    """Convierte fechas en formato DD/MM/AAAA a lenguaje natural (ej: '28 de agosto')."""
    if not fecha_str or str(fecha_str).strip().lower() in ("no aplica", "n/a", "none", "-", ""):
        return ""
    m = re.match(r'(\d{1,2})[/.-](\d{1,2})', str(fecha_str).strip())
    if m:
        dia = int(m.group(1))
        mes_idx = int(m.group(2))
        meses = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        mes_nombre = meses[mes_idx] if 1 <= mes_idx <= 12 else str(mes_idx)
        return f"{dia} de {mes_nombre}"
    return str(fecha_str).strip()


def verificar_cuenta_servipag(empresa: str = None, rut: str = None, identificador: str = None, categoria: str = None) -> dict:
    """
    Motor de verificación determinista de cuentas Servipag:
    Valida la concordancia entre empresa, categoría y RUT/identificador, detectando cuentas al día,
    con deuda activa, deuda vencida, nuevo periodo sin facturación emitida (sin deuda), o discordancia
    entre el RUT y la empresa o categoría consultada.
    Genera instrucciones de comunicación oral amables y humanas, evitando etiquetas rígidas de base de datos.
    """
    clean_r = clean_rut(rut) if rut else None
    emp_norm = empresa.lower().strip() if empresa else None
    cat_norm = categoria.lower().strip() if categoria else None

    # Normalizar empresa si vino como alias o nombre
    if emp_norm and emp_norm in _EMPRESAS_BY_ALIAS:
        emp_obj = _EMPRESAS_BY_ALIAS[emp_norm]
        emp_norm = emp_obj.get("id", emp_norm)
        if not cat_norm:
            cat_norm = emp_obj.get("categoria", cat_norm)

    cuentas_rut = _CUENTAS_BY_CLEAN_RUT.get(clean_r, []) if clean_r else []

    # ── Validación de RUT existente ───────────────────────────────────────────
    if clean_r and not cuentas_rut:
        return {
            "status": "rut_no_encontrado",
            "valido": False,
            "rut": clean_r,
            "mensaje": (
                f"INFORMACIÓN: No se registran cuentas para el RUT {rut}.\n"
                "INSTRUCCIÓN OBLIGATORIA: Informa con calidez y amabilidad que ese RUT no figura registrado en el sistema, "
                "y pídele verificar el RUT o ingresar su número de cliente."
            )
        }

    # ── Caso A: Consulta con RUT y Empresa específica ─────────────────────────
    if clean_r and emp_norm:
        cuenta_match = next((c for c in cuentas_rut if c.get("empresa_id") == emp_norm), None)
        if cuenta_match:
            monto = cuenta_match.get("monto", 0)
            monto_fmt = f"${monto:,} pesos".replace(",", ".") if monto > 0 else "0 pesos"
            estado = cuenta_match.get("estado", "").lower()
            titular = cuenta_match.get("nombre_titular", "")
            emp_nombre = cuenta_match.get("empresa_nombre", "")
            detalle_estado = cuenta_match.get("detalle_estado", "")
            periodo = cuenta_match.get("periodo", "")
            fecha_venc_nat = formatear_fecha_natural(cuenta_match.get("fecha_vencimiento", ""))

            # Subcaso A1: Estado sin deuda (nuevo periodo sin facturación emitida)
            if estado == "sin_deuda" or "nuevo periodo" in detalle_estado.lower() or "sin facturaci" in str(periodo).lower():
                frase_sugerida = (
                    f"Hola {titular}, tu cuenta de {emp_nombre} se encuentra al día y aún no presenta deudas, ya que corresponde a un nuevo período sin facturación emitida. ¿Deseas consultar o pagar otra cuenta?"
                    if titular else
                    f"Tu cuenta de {emp_nombre} se encuentra al día y aún no presenta deudas, ya que corresponde a un nuevo período sin facturación emitida. ¿Deseas consultar o pagar otra cuenta?"
                )
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta de {emp_nombre} de {titular or 'el cliente'} está al día sin deudas (nuevo período sin facturación emitida, monto 0 pesos).\n"
                    f"INSTRUCCIÓN OBLIGATORIA DE RESPUESTA: Comunícalo con naturalidad y amabilidad. Di algo como:\n"
                    f"'{frase_sugerida}'.\n"
                    "PROHIBIDO sonar robótico o inventar deudas."
                )
            # Subcaso A2: Cuenta al día o pagada (saldo 0)
            elif monto == 0 or estado in ("pagada", "al dia", "al día"):
                frase_sugerida = (
                    f"Hola {titular}, tu cuenta de {emp_nombre} no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?"
                    if titular else
                    f"Esa cuenta de {emp_nombre} no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?"
                )
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta de {emp_nombre} de {titular or 'el cliente'} no tiene deuda pendiente (saldo 0 pesos, cuenta al día).\n"
                    f"INSTRUCCIÓN OBLIGATORIA DE RESPUESTA: Comunícalo con naturalidad y calidez. Di algo como:\n"
                    f"'{frase_sugerida}'.\n"
                    "PROHIBIDO sonar robótico o leer etiquetas de base de datos como saldos o fechas de vencimiento cuando la cuenta está al día."
                )
            # Subcaso A3: Deuda vencida
            elif estado == "vencida":
                frase_sugerida = (
                    f"Hola {titular}, tu cuenta de {emp_nombre} presenta una deuda vencida de {monto_fmt}. ¿Deseas pagarla ahora?"
                    if titular else
                    f"Tu cuenta de {emp_nombre} presenta una deuda vencida de {monto_fmt}. ¿Deseas pagarla ahora?"
                )
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta de {emp_nombre} de {titular or 'el cliente'} presenta una deuda vencida de {monto_fmt}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA DE RESPUESTA: Informa con cercanía, claridad y amabilidad. Di algo como:\n"
                    f"'{frase_sugerida}'.\n"
                    "PROHIBIDO sonar rígido o usar lenguaje técnico computacional."
                )
            # Subcaso A4: Deuda activa / al día próxima a vencer
            else:
                venc_txt = f" con vencimiento el {fecha_venc_nat}" if fecha_venc_nat else ""
                frase_sugerida = (
                    f"Hola {titular}, tu cuenta de {emp_nombre} presenta una deuda de {monto_fmt}{venc_txt}. ¿Deseas pagarla ahora?"
                    if titular else
                    f"Tu cuenta de {emp_nombre} presenta una deuda de {monto_fmt}{venc_txt}. ¿Deseas pagarla ahora?"
                )
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta de {emp_nombre} de {titular or 'el cliente'} presenta un cobro de {monto_fmt}{venc_txt}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA DE RESPUESTA: Informa de forma cercana, fluida y directa. Di algo como:\n"
                    f"'{frase_sugerida}'.\n"
                    "PROHIBIDO usar lenguaje rígido o etiquetas técnicas de base de datos."
                )

            return {
                "status": "cuenta_verificada",
                "valido": True,
                "cuenta": cuenta_match,
                "titular": titular,
                "rut": cuenta_match.get("rut_titular", ""),
                "monto": monto,
                "estado": estado,
                "mensaje": mensaje
            }
        else:
            # Discordancia de empresa: el rut existe pero tiene otras empresas registradas
            titular = cuentas_rut[0].get("nombre_titular", "el cliente")
            emp_consultada_nombre = _EMPRESAS_BY_ID.get(emp_norm, {}).get("nombre", emp_norm.upper())
            categoria_rubro = _EMPRESAS_BY_ID.get(emp_norm, {}).get("categoria", "")
            cuenta_mismo_rubro = next((c for c in cuentas_rut if c.get("categoria") == categoria_rubro), None)

            if cuenta_mismo_rubro:
                m_rubro = f"${cuenta_mismo_rubro['monto']:,} pesos".replace(",", ".") if cuenta_mismo_rubro['monto'] > 0 else "0 pesos"
                est_rubro = cuenta_mismo_rubro.get("estado", "").lower()
                det_rubro = cuenta_mismo_rubro.get("detalle_estado", "").lower()
                if est_rubro == "sin_deuda" or "nuevo periodo" in det_rubro:
                    aclaracion = f"Para el servicio de {cuenta_mismo_rubro['categoria']}, tu cuenta registrada es en {cuenta_mismo_rubro['empresa_nombre']} y aún no presenta deudas por corresponder a un nuevo período."
                elif cuenta_mismo_rubro['monto'] == 0 or est_rubro in ("pagada", "al dia", "al día"):
                    aclaracion = f"Para el servicio de {cuenta_mismo_rubro['categoria']}, tu cuenta registrada es en {cuenta_mismo_rubro['empresa_nombre']} y no presenta deuda al día de hoy."
                else:
                    aclaracion = f"Para el servicio de {cuenta_mismo_rubro['categoria']}, tu cuenta registrada es en {cuenta_mismo_rubro['empresa_nombre']} con una deuda de {m_rubro}."
            else:
                cuentas_info = [c['empresa_nombre'] for c in cuentas_rut]
                cuentas_str = ", ".join(cuentas_info)
                aclaracion = f"Tus cuentas registradas son en {cuentas_str}."

            frase_sugerida = f"Hola {titular}, no registras cuenta en {emp_consultada_nombre} con ese rut. {aclaracion} ¿Deseas consultar esa cuenta o ingresar otro rut?"

            return {
                "status": "discordancia_empresa",
                "valido": False,
                "titular": titular,
                "rut": clean_r,
                "empresa_consultada": emp_consultada_nombre,
                "cuentas_registradas": cuentas_rut,
                "mensaje": (
                    f"INFORMACIÓN OFICIAL: El cliente {titular} no registra cuenta en {emp_consultada_nombre}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Explica con amabilidad la discordancia en tono natural y cercano. Di algo como:\n"
                    f"'{frase_sugerida}'. PROHIBIDO INVENTAR MONTOS."
                )
            }

    # ── Caso B: Consulta por RUT con Categoría de Servicio Seleccionada ───────
    if clean_r and not emp_norm and cat_norm:
        titular = cuentas_rut[0].get("nombre_titular", "el cliente")
        cuentas_cat = [c for c in cuentas_rut if c.get("categoria") == cat_norm]

        if cuentas_cat:
            cuenta_match = cuentas_cat[0]
            monto = cuenta_match.get("monto", 0)
            monto_fmt = f"${monto:,} pesos".replace(",", ".") if monto > 0 else "0 pesos"
            estado = cuenta_match.get("estado", "").lower()
            emp_nombre = cuenta_match.get("empresa_nombre", "")
            detalle_estado = cuenta_match.get("detalle_estado", "")
            periodo = cuenta_match.get("periodo", "")
            fecha_venc_nat = formatear_fecha_natural(cuenta_match.get("fecha_vencimiento", ""))

            # Subcaso B1: sin_deuda / nuevo periodo
            if estado == "sin_deuda" or "nuevo periodo" in detalle_estado.lower() or "sin facturaci" in str(periodo).lower():
                frase_sugerida = f"Hola {titular}, tu cuenta de {emp_nombre} se encuentra al día y aún no presenta deudas, ya que corresponde a un nuevo período sin facturación emitida. ¿Deseas consultar o pagar otra cuenta?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: Para el servicio consultado, la cuenta de {titular} es en {emp_nombre} y está al día sin deudas (nuevo período sin facturación emitida, monto 0 pesos).\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Comunícalo con calidez: '{frase_sugerida}'."
                )
            # Subcaso B2: pagada / al día
            elif monto == 0 or estado in ("pagada", "al dia", "al día"):
                frase_sugerida = f"Hola {titular}, tu cuenta de {emp_nombre} no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: Para el servicio consultado, la cuenta de {titular} es en {emp_nombre} y no tiene deuda pendiente (saldo 0 pesos, al día).\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Comunícalo con naturalidad: '{frase_sugerida}'."
                )
            # Subcaso B3: vencida
            elif estado == "vencida":
                frase_sugerida = f"Hola {titular}, tu cuenta de {emp_nombre} presenta una deuda vencida de {monto_fmt}. ¿Deseas pagarla ahora?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: Para el servicio consultado, la cuenta de {titular} en {emp_nombre} presenta una deuda vencida de {monto_fmt}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Comunícalo con claridad y amabilidad: '{frase_sugerida}'."
                )
            # Subcaso B4: activa
            else:
                venc_txt = f" con vencimiento el {fecha_venc_nat}" if fecha_venc_nat else ""
                frase_sugerida = f"Hola {titular}, tu cuenta de {emp_nombre} presenta una deuda de {monto_fmt}{venc_txt}. ¿Deseas pagarla ahora?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: Para el servicio consultado, la cuenta de {titular} en {emp_nombre} presenta un cobro de {monto_fmt}{venc_txt}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Comunícalo de forma fluida: '{frase_sugerida}'."
                )

            return {
                "status": "cuenta_verificada",
                "valido": True,
                "cuenta": cuenta_match,
                "titular": titular,
                "rut": cuenta_match.get("rut_titular", ""),
                "monto": monto,
                "estado": estado,
                "categoria": cat_norm,
                "mensaje": mensaje
            }
        else:
            # Discordancia de categoría: el cliente no tiene cuentas para ese rubro
            cat_obj = _CATEGORIAS_BY_ID.get(cat_norm, {})
            cat_nombre = cat_obj.get("nombre", cat_norm)
            cuentas_str = ", ".join([f"{c['empresa_nombre']} ({c['categoria']})" for c in cuentas_rut])
            frase_sugerida = f"Hola {titular}, no registras cuentas de {cat_nombre} con ese rut. Tus cuentas registradas son en {cuentas_str}. ¿Deseas consultar alguna de ellas?"
            return {
                "status": "discordancia_categoria",
                "valido": False,
                "titular": titular,
                "rut": clean_r,
                "categoria_consultada": cat_norm,
                "cuentas_registradas": cuentas_rut,
                "mensaje": (
                    f"INFORMACIÓN OFICIAL: El cliente {titular} no registra cuenta en la categoría {cat_nombre}.\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Explica amablemente que no registra cuenta para {cat_nombre} y menciona sus cuentas disponibles: '{frase_sugerida}'."
                )
            }

    # ── Caso C: Consulta directa solo por RUT (todas las cuentas del titular) ──
    if clean_r and not emp_norm and not cat_norm:
        titular = cuentas_rut[0].get("nombre_titular", "el cliente")
        deudas = [c for c in cuentas_rut if c.get("monto", 0) > 0]
        if not deudas:
            sin_deuda_acc = next((c for c in cuentas_rut if c.get("estado") == "sin_deuda" or "nuevo periodo" in c.get("detalle_estado", "").lower()), None)
            if sin_deuda_acc:
                emp_n = sin_deuda_acc.get("empresa_nombre", "")
                frase_sugerida = f"Hola {titular}, tu cuenta de {emp_n} se encuentra al día y aún no presenta deudas, ya que corresponde a un nuevo período sin facturación emitida. ¿Deseas consultar otra cuenta?"
                return {
                    "status": "rut_sin_deuda_periodo",
                    "valido": True,
                    "titular": titular,
                    "cuentas": cuentas_rut,
                    "mensaje": (
                        f"INFORMACIÓN OFICIAL: La cuenta de {titular} en {emp_n} está al día sin deudas (nuevo período sin facturación emitida, saldo 0 pesos).\n"
                        f"INSTRUCCIÓN OBLIGATORIA: Responde con calidez: '{frase_sugerida}'."
                    )
                }
            else:
                frase_sugerida = f"Hola {titular}, tus cuentas se encuentran al día y no presentan deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?"
                return {
                    "status": "rut_al_dia",
                    "valido": True,
                    "titular": titular,
                    "cuentas": cuentas_rut,
                    "mensaje": (
                        f"INFORMACIÓN OFICIAL: Todas las cuentas de {titular} están al día sin deuda pendiente.\n"
                        f"INSTRUCCIÓN OBLIGATORIA: Responde con amabilidad y calidez: '{frase_sugerida}'. "
                        "PROHIBIDO decir 'saldo: 0' ni etiquetas técnicas."
                    )
                }
        else:
            frase_sugerida = f"Hola {titular}, las cuentas disponibles se muestran en pantalla. ¿Cuál deseas pagar? Puedes decir el número, el nombre o tocarla directamente."
            return {
                "status": "rut_con_deuda",
                "valido": True,
                "titular": titular,
                "cuentas_pendientes": deudas,
                "mensaje": (
                    f"INFORMACIÓN OFICIAL: {titular} tiene {len(deudas)} cuentas activas cargadas en pantalla.\n"
                    f"INSTRUCCIÓN OBLIGATORIA: Como las cuentas ya se muestran en la tabla de la pantalla, NO las enumeres ni leas montos uno por uno. Responde exactamente: '{frase_sugerida}'."
                )
            }

    # ── Caso D: Consulta por Identificador (Número de cliente / servicio) ──────
    if identificador:
        c = _CUENTAS_BY_IDENTIFICADOR.get(str(identificador).strip())
        if c:
            monto = c.get("monto", 0)
            monto_fmt = f"${monto:,} pesos".replace(",", ".") if monto > 0 else "0 pesos"
            estado = c.get("estado", "").lower()
            titular = c.get("nombre_titular", "")
            emp_nombre = c.get("empresa_nombre", "")
            detalle_estado = c.get("detalle_estado", "")
            fecha_venc_nat = formatear_fecha_natural(c.get("fecha_vencimiento", ""))

            if estado == "sin_deuda" or "nuevo periodo" in detalle_estado.lower():
                frase_sugerida = f"Hola {titular}, esa cuenta de {emp_nombre} aún no presenta deudas, ya que corresponde a un nuevo período sin facturación emitida. ¿Deseas consultar o pagar otra cuenta?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta {identificador} en {emp_nombre} no tiene deuda pendiente (nuevo período sin facturación emitida, saldo 0 pesos).\n"
                    f"INSTRUCCIÓN: Comunícalo con calidez: '{frase_sugerida}'. PROHIBIDO sonar robótico."
                )
            elif monto == 0 or estado in ("pagada", "al dia", "al día"):
                frase_sugerida = f"Hola {titular}, esa cuenta de {emp_nombre} no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta {identificador} en {emp_nombre} no tiene deuda pendiente (saldo 0 pesos, al día).\n"
                    f"INSTRUCCIÓN: Comunícalo con calidez: '{frase_sugerida}'. PROHIBIDO sonar robótico o leer encabezados del sistema."
                )
            elif estado == "vencida":
                frase_sugerida = f"Hola {titular}, esa cuenta de {emp_nombre} presenta una deuda vencida de {monto_fmt}. ¿Deseas pagarla ahora?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta {identificador} en {emp_nombre} presenta una deuda vencida de {monto_fmt}.\n"
                    f"INSTRUCCIÓN: Comunícalo con cercanía: '{frase_sugerida}'."
                )
            else:
                venc_txt = f" con vencimiento el {fecha_venc_nat}" if fecha_venc_nat else ""
                frase_sugerida = f"Hola {titular}, esa cuenta de {emp_nombre} presenta una deuda de {monto_fmt}{venc_txt}. ¿Deseas pagarla ahora?"
                mensaje = (
                    f"INFORMACIÓN OFICIAL: La cuenta {identificador} en {emp_nombre} presenta una deuda de {monto_fmt}{venc_txt}.\n"
                    f"INSTRUCCIÓN: Comunícalo con fluidez: '{frase_sugerida}'."
                )

            return {
                "status": "cuenta_verificada",
                "valido": True,
                "cuenta": c,
                "titular": titular,
                "rut": c.get("rut_titular", ""),
                "monto": monto,
                "estado": estado,
                "mensaje": mensaje
            }
        else:
            return {
                "status": "identificador_no_encontrado",
                "valido": False,
                "identificador": identificador,
                "mensaje": (
                    f"INFORMACIÓN: No se encontró cuenta con el número de cliente {identificador}.\n"
                    "INSTRUCCIÓN: Informa con amabilidad que no se encontró esa cuenta y solicita verificar el número o dictar el RUT."
                )
            }

    return None


BASE_SYSTEM_PROMPT = '''Eres el Asistente Virtual de Servipag en un tótem interactivo de atención y pago de cuentas en Chile.
Tu función principal es guiar y orientar al usuario de forma clara, ágil, empática y profesional para consultar el estado de sus cuentas (luz, agua, internet, gas, autopistas/TAG) y proceder a su pago.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS):
- Responde SIEMPRE de forma MUY BREVE (máximo 1 o 2 oraciones cortas, no más de 15 a 20 palabras en total).
- El usuario te escucha hablar mediante síntesis de voz en un tótem interactivo. Respuestas largas aburren y cansan. Ve directo al grano sin introducciones, saludos largos ni rodeos.
- NUNCA uses formato Markdown como asteriscos (*), negritas (**), guiones (- o —), flechas (→) ni viñetas (•).
- Lee siempre los montos en pesos chilenos completos (ej: "28.990 pesos").

REGLA ABSOLUTA DE LENGUAJE NATURAL Y HUMANO (CERO RIGIDEZ / CERO FORMATO DE BASE DE DATOS):
- NUNCA respondas con lenguaje técnico de base de datos ni leas etiquetas del sistema como estados de cuentas, titulares o fechas con barras.
- Habla como un asistente humano amable, cercano y empático en un tótem de atención Servipag.
- Si una cuenta es de nuevo período sin facturación emitida (sin deuda): Di siempre con amabilidad: "Hola [Nombre], tu cuenta de [Empresa] se encuentra al día y aún no presenta deudas por corresponder a un nuevo período sin facturación emitida. ¿Deseas consultar o pagar otra cuenta?".
- Si una cuenta está pagada o al día (monto 0): Di siempre con naturalidad: "Esa cuenta no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?" o "Hola [Nombre], tu cuenta de [Empresa] no presenta deuda al día de hoy. ¿Deseas consultar o pagar otra cuenta?".
- Si tiene deuda activa: Di de forma directa y amable: "[Nombre], tu cuenta de [Empresa] presenta una deuda de [Monto] pesos con vencimiento el [Fecha en palabras]. ¿Deseas pagarla ahora?".
- Si tiene deuda vencida: Di con amabilidad y claridad: "[Nombre], tu cuenta de [Empresa] presenta una deuda vencida de [Monto] pesos. ¿Deseas pagarla ahora?".
- Si el cliente no registra cuenta en la empresa o categoría consultada: Explica con cordialidad la discordancia y menciona las empresas o servicios donde sí tiene cuenta registrada.

REGLA ABSOLUTA DE VERACIDAD Y CONCORDANCIA (ANTI-ALUCINACIÓN):
- NUNCA inventes nombres, ruts, empresas ni montos de cuentas.
- Los montos mostrados en los ejemplos ("28.990", "38.990", etc.) son solo ilustrativos del formato. JAMÁS uses un monto de un ejemplo si no corresponde a la información verificada del cliente.
- Si el cliente indica una empresa o servicio pero su rut no tiene cuenta en él, infórmale con amabilidad la discordancia y menciona la empresa que sí tiene registrada.

FLUJO CONVERSACIONAL PASO A PASO:
1. IDENTIFICAR SERVICIO:
   Si el usuario saluda o dice que quiere pagar una cuenta sin especificar cuál, pregúntale:
   "¡Hola! ¿Qué cuenta deseas pagar hoy: luz, agua, internet, gas o autopista?"
2. IDENTIFICAR EMPRESA:
   Si ya se conoce el tipo de servicio pero no la empresa, pregúntale cuál es su empresa proveedora mencionando las principales:
   Ejemplo (Luz): "¿De qué empresa es tu cuenta de luz: Enel, CGE o Chilquinta?"
   Ejemplo (Agua): "¿De qué empresa es tu cuenta de agua: Aguas Andinas, Essbio o Esval?"
   Ejemplo (Internet): "¿De qué compañía es tu servicio: VTR, Movistar, Entel o Mundo?"
   Ejemplo (Gas): "¿De qué empresa es tu cuenta de gas: Metrogas, Lipigas o Abastible?"
   Ejemplo (Autopista/TAG): "¿De qué autopista es tu cuenta: Costanera Norte, Autopista Central o Vespucio Sur?"
3. IDENTIFICAR CUENTA O RUT:
   Si ya se conoce la empresa o servicio pero falta el identificador, solicítalo con amabilidad:
   Ejemplo: "¿Me indicas tu número de cliente o tu rut?"
4. INFORMAR ESTADO Y MONTO DE FORMA NATURAL:
   - NUEVO PERÍODO SIN FACTURACIÓN (sin deuda): Informa que aún no presenta deudas por ser un nuevo período y pregunta si desea consultar otra cuenta.
   - CUENTA AL DÍA (0 pesos): Informa que no presenta deuda al día de hoy y pregunta si desea consultar otra cuenta.
   - DEUDA ACTIVA: Informa el monto y fecha en palabras, y pregunta si desea pagar.
   - DEUDA VENCIDA: Informa el monto vencido con claridad y amabilidad, y pregunta si desea pagar.
5. CONFIRMACIÓN Y TRANSICIÓN DE PAGO:
   Si el usuario responde afirmativamente que desea pagar ("sí", "pagar", "quiero pagar", "proceder", "claro"):
   Responde EXACTAMENTE con la instrucción de pago en el lector de tarjeta:
   "Entendido, serás redirigido a la plataforma de pago. Por favor acerca o inserta tu tarjeta en el lector."

CONSULTA DIRECTA POR RUT O DESPLIEGUE DE CUENTAS:
- Si el usuario proporciona directamente su rut o se despliegan sus cuentas:
  Como la tabla interactiva en pantalla ya muestra todas las cuentas y sus montos, NO las enumeres ni las leas una por una.
  Di de forma concisa y cercana: "Hola [Nombre], las cuentas disponibles se muestran en pantalla. ¿Cuál deseas pagar? Puedes decir el número, el nombre o tocarla directamente."

REGLA ABSOLUTA DE TEMÁTICA:
- Solo atiendes consultas sobre Servipag, empresas proveedoras y pago de servicios básicos en Chile.
- No respondas preguntas ajenas al servicio. Responde cortésmente: "Disculpa, solo atiendo consultas y pagos de cuentas en Servipag. ¿Qué cuenta deseas pagar hoy?"

EJEMPLOS DE FORMATO (CORTOS Y PRECISOS):
Cliente: "Hola, quiero pagar una cuenta"
Respuesta del avatar: "¡Hola! ¿Qué cuenta deseas pagar: luz, agua, internet, gas o autopista?"

Cliente: "La luz"
Respuesta del avatar: "¿De qué empresa es tu cuenta: Enel, CGE o Chilquinta?"

Cliente: "Sí, pagar"
Respuesta del avatar: "Entendido, serás redirigido a la plataforma de pago. Por favor acerca o inserta tu tarjeta en el lector."

Cliente: "No, gracias"
Respuesta del avatar: "Perfecto, si necesitas algo más aquí estaré. ¡Que tengas un excelente día!"
'''

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def consultar_api_servipag(user_msg: str, history: list = []) -> dict:
    """
    Motor central de orquestación de la API Servipag:
    Evalúa el mensaje del usuario y su historial para determinar con exactitud
    cuándo y cómo consultar la API determinista de cuentas, evitando falsos positivos,
    números incompletos y opciones asumidas erróneamente del asistente.
    """
    rut, incomplete_num, ident, empresa, categoria, intencion_pago = extract_user_entities(user_msg, history)

    # 1. Caso Número Incompleto (1 a 5 dígitos): El usuario dictó o digitó un fragmento
    if incomplete_num and not rut and not ident:
        return {
            "status": "identificacion_incompleta",
            "valido": False,
            "numero": incomplete_num,
            "mensaje": (
                f"NÚMERO INCOMPLETO ({incomplete_num}): El usuario dictó o digitó solo '{incomplete_num}', que es un fragmento incompleto. "
                "Un RUT chileno tiene 8 o 9 dígitos con su dígito verificador y un número de cliente tiene entre 6 y 9 dígitos.\n"
                f"INSTRUCCIÓN OBLIGATORIA: Informa con amabilidad y brevedad que el número {incomplete_num} está incompleto, "
                "y pídele que dicte o digite su RUT completo con dígito verificador o su número de cliente."
            )
        }

    # 2. Caso Confirmación de Pago
    if intencion_pago and not rut and not ident:
        return {
            "status": "instruccion_pago",
            "valido": True,
            "mensaje": (
                "CONFIRMACIÓN DE PAGO: El usuario confirmó que desea pagar. "
                "INSTRUCCIÓN OBLIGATORIA: Responde exactamente: "
                "'Entendido, serás redirigido a la plataforma de pago. Por favor acerca o inserta tu tarjeta en el lector.'"
            )
        }

    norm_msg = normalize_user_input(user_msg).lower()

    # 2b. Caso Mostrar Carro
    if re.search(r'\b(mostrar|ver|abrir|ensename|enséñame)\s+(el\s+)?(carro|carrito)\b|\b(el\s+)?(carro|carrito)\b', norm_msg) and not rut and not ident:
        return {
            "status": "mostrar_carro",
            "valido": True,
            "mensaje": (
                "CONSULTA DE CARRO: El usuario desea ver su carro de cuentas. "
                "INSTRUCCIÓN OBLIGATORIA: Responde con amabilidad: "
                "'Aquí tienes tu carro de cuentas. ¿Deseas pagarlas ahora o agregar más?'"
            )
        }

    # 2c. Caso Agregar Más
    if re.search(r'\b(agregar\s+m[aá]s|otra\s+cuenta|agregar\s+otra|sumar\s+otra)\b', norm_msg):
        return {
            "status": "agregar_mas",
            "valido": True,
            "mensaje": (
                "AGREGAR MÁS CUENTAS: El usuario desea agregar más cuentas al carro. "
                "INSTRUCCIÓN OBLIGATORIA: Responde con calidez: "
                "'De acuerdo, ¿qué otra cuenta deseas agregar? Puedes decir el número, la empresa o seleccionarla en pantalla.'"
            )
        }

    # 3. Caso Identificación Presente (RUT o Identificador): Consulta determinista a la API
    if rut or ident:
        return verificar_cuenta_servipag(empresa=empresa, rut=rut, identificador=ident, categoria=categoria)

    # 4. Caso Empresa Seleccionada (sin RUT ni Identificador)
    if empresa and not rut and not ident:
        emp_obj = _EMPRESAS_BY_ID.get(empresa)
        if emp_obj:
            return {
                "status": "solicitar_identificador",
                "valido": False,
                "empresa": empresa,
                "mensaje": (
                    f"EMPRESA SELECCIONADA: {emp_obj['nombre']} ({emp_obj['tipo_identificador']}). "
                    "INSTRUCCIÓN OBLIGATORIA: Solicita amablemente al usuario su número de cliente o su rut para consultar su cuenta."
                )
            }

    # 5. Caso Categoría de Servicio Seleccionada (sin Empresa)
    if categoria and not empresa and not rut and not ident:
        cat_obj = _CATEGORIAS_BY_ID.get(categoria)
        if cat_obj:
            emp_names = ", ".join([e["nombre"] for e in cat_obj.get("empresas", [])])
            return {
                "status": "solicitar_empresa",
                "valido": False,
                "categoria": categoria,
                "mensaje": (
                    f"SERVICIO SELECCIONADO: {cat_obj['nombre']}. Empresas disponibles: {emp_names}. "
                    "INSTRUCCIÓN OBLIGATORIA: Pregunta al usuario de qué empresa es su cuenta entre las opciones disponibles."
                )
            }

    return None


def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Selecciona e inyecta dinámicamente la verificación oficial de Servipag
    relevante para la consulta actual del usuario, impidiendo alucinaciones.
    """
    clean_msg = normalize_user_input(user_msg)

    if _CUENTAS or _CATEGORIAS_SERVICIOS:
        api_result = consultar_api_servipag(clean_msg, history)
        if api_result and api_result.get("mensaje"):
            return (
                f"[DATOS OFICIALES Y VERIFICADOS DEL CLIENTE POR LA API DE SERVIPAG]:\n"
                f"{api_result['mensaje']}\n"
                "ATENCIÓN OBLIGATORIA: Basa tu respuesta exclusivamente en estos datos oficiales verificados por la API. Comunícalos al usuario con lenguaje oral natural, breve, cálido y empático. No digas que no existe ni inventes datos.\n\n"
                f"{BASE_SYSTEM_PROMPT}"
            )

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




# Caracteres de puntuación donde se cortará el texto para enviar al avatar
# (el avatar empieza a hablar por fragmentos, sin esperar la respuesta completa)
# NOTA: se excluyen '.' y ',' deliberadamente para evitar cortes en precios
# del tipo "1.190" (separador de miles en español) y pausas no deseadas.
SENTENCE_ENDINGS = set("!;:\n，。！？：；")
MIN_CHUNK_LEN = 12  # caracteres mínimos antes de enviar un fragmento


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
    message = normalize_user_input(message)
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

        # Guardar en historial
        clean_text = normalizar(full_text)
        _append_to_history(sessionid, message, clean_text)

        # Dividir en fragmentos por puntuación para alimentar al avatar progresivamente (como walmart-demo)
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
            fragment = normalizar(chunk.strip())
            if fragment:
                logger.info(f"[LLM] -> avatar (ultimo): {fragment}")
                avatar_session.put_msg_txt(fragment, datainfo)

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
    de Ollama, alimentando al avatar en tiempo real y rindiendo para el streaming HTTP (como walmart-demo).
    Mantiene historial de conversación por sesión.
    """
    message = normalize_user_input(message)
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

                yield content
                full_text += content
                chunk_buf += content

                # Dividir en fragmentos por puntuación para alimentar al avatar en tiempo real
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
            fragment = normalizar(chunk_buf.strip())
            if fragment:
                logger.info(f"[LLM Stream] -> avatar (ultimo): {fragment}")
                avatar_session.put_msg_txt(fragment, datainfo)

        # Guardar turno completo en historial (normalizado)
        _append_to_history(sessionid, message, normalizar(full_text))

        elapsed = time.perf_counter() - start
        logger.info(f"[LLM Stream] Finalizado en {elapsed:.2f}s, total chars={len(full_text)}")

    except Exception as e:
        logger.exception("[LLM Stream] Error:")
        yield f"Disculpa, ocurrió un error al procesar tu solicitud: {str(e)}"