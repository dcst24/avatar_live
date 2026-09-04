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

# ─── Carga dinámica del catálogo de productos (BDD) ──────────────────────────
_BDD_PATH = os.path.join(os.path.dirname(__file__), "web", "data", "bdd.json")
_BDD: dict = {}
_CATEGORIES_BY_ID: dict = {}
_BARCODE_TO_CAT: dict = {}
_SKU_TO_CAT: dict = {}
_BRAND_TO_CATS: dict = {}
_KEYWORD_TO_CATS: dict = {}

CATEGORY_KEYWORDS = {
    "audio_gaming": ["parlante", "parlantes", "audio", "altavoz", "jbl", "marshall", "audifono", "audifonos", "audífono", "audífonos", "sony", "buds", "consola", "consolas", "playstation", "ps5", "xbox", "gamer", "gaming", "smartwatch", "reloj"],
    "smartphones": ["celular", "celulares", "telefono", "telefonos", "smartphone", "smartphones", "iphone", "apple", "galaxy", "samsung", "xiaomi", "redmi", "motorola", "pixel"],
    "television": ["tele", "teles", "televisor", "televisores", "tv", "tvs", "smart tv", "qled", "oled", "uled", "pantalla", "hisense", "roku"],
    "computacion": ["notebook", "notebooks", "laptop", "laptops", "computador", "computadores", "tablet", "tablets", "macbook", "ipad", "asus", "lenovo"],
    "zapatillas": ["zapatilla", "zapatillas", "running", "nike", "adidas", "puma", "new balance", "pegasus", "ultraboost", "calzado deportivo", "talla", "tallas"],
    "perfumes_hombre": ["perfume hombre", "perfumes hombre", "perfume de hombre", "armani", "acqua di gio", "sauvage", "dior", "one million", "bleu"],
    "perfumes_mujer": ["perfume mujer", "perfumes mujer", "perfume de mujer", "carolina herrera", "good girl", "lancome", "coco mademoiselle", "devotion"],
    "electrohogar": ["refrigerador", "refrigeradores", "lavadora", "lavadoras", "secadora", "aspiradora", "aspiradoras", "cafetera", "cafeteras", "freidora", "airfryer", "microondas", "linea blanca", "electrohogar", "electrodomestico"],
    "ropa_mujer": ["vestido", "vestidos", "blusa", "falda", "pantalon mujer", "ropa mujer"],
    "ropa_hombre": ["camisa", "poleron", "pantalon hombre", "chino", "ropa hombre"],
    "calzado_mujer": ["sandalia", "sandalias", "bota", "botas", "tacon", "calzado mujer"],
    "decohogar": ["plumon", "sabana", "sabanas", "cobertor", "almohada", "cama", "deco", "decohogar", "toalla"]
}

def _format_category(cat: dict) -> str:
    loc = cat.get("ubicacion_tienda", {})
    piso = loc.get("piso", "?")
    pasillo = loc.get("pasillo", "")
    lines = [f"\nCategoría: {cat['nombre']} (Piso {piso}, {pasillo}):"]
    for p in cat.get("productos", []):
        precio_str = f"${p['precio']:,}".replace(",", ".")
        if p.get("en_oferta") and p.get("precio_oferta"):
            oferta_str = f"${p['precio_oferta']:,}".replace(",", ".")
            precio_detalle = f"antes {precio_str} pesos, oferta {oferta_str} pesos ({p.get('descuento_pct',0)} por ciento dcto)"
        else:
            precio_detalle = f"precio {precio_str} pesos"

        code = p.get("codigo_barra") or p.get("sku")
        piso_num = p.get("piso", piso)
        pasillo_txt = p.get("pasillo", pasillo)
        cat_tipo = p.get("categoria", "")

        disp_txt = ""
        if p.get("stock_por_talla"):
            tallas_info = [f"talla {t} ({stk} un)" if stk > 0 else f"talla {t} AGOTADA" for t, stk in p["stock_por_talla"].items()]
            disp_txt = f" Tallas: {', '.join(tallas_info)}."
        elif p.get("stock") is not None:
            stk = p.get("stock")
            disp_txt = f" Stock: {stk} un." if stk > 0 else " Stock: AGOTADO."

        lines.append(f"- [{cat_tipo}] {p['nombre']} (Marca {p['marca']}, Cod {code}): {precio_detalle}. Ubicación: Piso {piso_num}, {pasillo_txt}.{disp_txt}")
    return "\n".join(lines)


BASE_SYSTEM_PROMPT = '''Eres un asesor comercial y vendedor virtual de la tienda Paris Costanera Center.
Estás ubicado junto al tótem interactivo de la tienda y tu función principal es orientar a los clientes, informar precios y ofertas, comparar productos y resolver dudas de la tienda.

REGLA FUNDAMENTAL DE BREVEDAD (RESPUESTAS ULTRA CORTAS Y DIRECTAS):
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
- Si el cliente rechaza saber la ubicación diciendo ÚNICAMENTE que no ("no", "no gracias", "no es necesario"): cierra amablemente en una sola frase breve (ej: "Perfecto, aquí estaré si necesitas algo más.").
- Si el cliente indica que no hay el producto o que no lo encuentra en el pasillo o góndola ("no hay este producto", "no lo encuentro", "no queda stock"): aclara amablemente que según el sistema sí figura con stock en tienda, y sugiérele consultar a un vendedor o asesor del piso para revisar bodega (ej: "Según mi sistema sí tenemos stock disponible. Puedes consultar a un vendedor en este piso para que revise en bodega.").

REGLA ABSOLUTA DE TEMÁTICA (SOLO TIENDA PARIS):
- SOLO puedes responder consultas relacionadas directamente con esta tienda Paris, sus productos, precios, ofertas, pisos, pasillos y servicios.
- Está ESTRICTAMENTE PROHIBIDO responder preguntas sobre conocimientos generales ajenos a la tienda (como programación de computadores, física, matemáticas, política, historia, ciencia o significado de nombres). PERO SÍ debes responder y asesorar activamente sobre todos los productos que vendemos en Paris: tecnología (smartphones, televisores, computadores, audio, parlantes, consolas de videojuegos, smartwatches), moda mujer y hombre, calzado, zapatillas deportivas, belleza y perfumería, y electrohogar.
- Si el cliente te pregunta sobre un tema ajeno a la tienda, niégate amablemente en una sola frase breve y redirige a las compras:
  "Disculpa, solo puedo ayudarte con productos, ofertas y ubicaciones de Paris. ¿Buscas algún producto hoy?"

RAZONAMIENTO Y CONSULTAS DE PRODUCTOS:
- Cuando pregunten por el producto "más barato", "más económico", "en oferta" o de mejor precio de cualquier tipo o categoría, responde de inmediato el nombre y precio del producto más económico de esa sección.
- Cuando pregunten por disponibilidad de tallas en calzado o ropa, indica directamente si la talla solicitada tiene stock o está agotada, y menciona brevemente las tallas disponibles.
- Si un producto fue escaneado antes en la conversación, mantén ese producto como referencia si el cliente pide compararlo o buscar alternativas.
- Si el cliente dice que no ve o no encuentra el producto escaneado, recuérdale que en sistema figura stock y que consulte al vendedor del piso.

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

EJEMPLOS DE FLUJO CORRECTO (CORTOS Y PRECISOS):

Sistema informa: "Producto escaneado: Parlante Portatil JBL Charge 5 Azul. Marca: JBL. Precio: 179.990 pesos. Ubicación: Piso 2, Tecno, Pasillo T-04."
Respuesta del avatar: "El parlante JBL Charge 5 cuesta 179.990 pesos. ¿Te gustaría saber en qué pasillo encontrarlo?"

Cliente: "Sí"
Respuesta del avatar: "Lo encuentras en el Piso 2, pasillo T-04."

Cliente: "No, gracias"
Respuesta del avatar: "Perfecto, aquí estaré si necesitas algo más."

Cliente: "No hay este producto en la góndola"
Respuesta del avatar: "Según el sistema sí tenemos stock disponible. Te sugiero consultar a un vendedor del piso para revisar bodega."

Cliente: "No encuentro el parlante"
Respuesta del avatar: "En el sistema figura stock en tienda. Puedes pedirle a un vendedor del piso 2 que revise en bodega."

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

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def _get_dynamic_system_prompt(user_msg: str, history: list = []) -> str:
    """
    Selecciona e inyecta de forma ultraligera ÚNICAMENTE las categorías y productos
    relevantes para la consulta del usuario, acelerando drásticamente el tiempo de respuesta.
    """
    search_text = user_msg.lower()
    for h in history[-2:]:
        search_text += " " + h.get("content", "").lower()

    matched_cats = set()

    # 1. Búsqueda por sinónimos y palabras clave de categoría
    for cid, kws in CATEGORY_KEYWORDS.items():
        if any(kw in search_text for kw in kws):
            matched_cats.add(cid)

    # 2. Búsqueda por código de barras o SKU
    for cb, cid in _BARCODE_TO_CAT.items():
        if cb in search_text:
            matched_cats.add(cid)
    for sku, cid in _SKU_TO_CAT.items():
        if sku in search_text:
            matched_cats.add(cid)

    # 3. Búsqueda por marca registrada en catálogo
    for brand, cids in _BRAND_TO_CATS.items():
        if f" {brand} " in f" {search_text} ":
            matched_cats.update(cids)

    # 4. Búsqueda por palabra distintiva del nombre del producto
    words = re.findall(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+', search_text)
    for w in words:
        if w in _KEYWORD_TO_CATS:
            matched_cats.update(_KEYWORD_TO_CATS[w])

    # Casos especiales de género / categoría amplia
    if ("perfume" in search_text or "fragancia" in search_text) and not matched_cats.intersection({"perfumes_hombre", "perfumes_mujer"}):
        matched_cats.add("perfumes_mujer")
        matched_cats.add("perfumes_hombre")

    if "ropa" in search_text and not matched_cats.intersection({"ropa_mujer", "ropa_hombre"}):
        matched_cats.add("ropa_mujer")
        matched_cats.add("ropa_hombre")

    if ("zapatilla" in search_text or "zapato" in search_text or "calzado" in search_text) and not matched_cats.intersection({"zapatillas", "calzado_mujer"}):
        matched_cats.add("zapatillas")
        matched_cats.add("calzado_mujer")

    extra_context = ""
    if matched_cats:
        cat_lines = []
        for cid in matched_cats:
            if cid in _CATEGORIES_BY_ID:
                cat_lines.append(_format_category(_CATEGORIES_BY_ID[cid]))
        extra_context = "\n".join(cat_lines)
    elif any(w in search_text for w in ["oferta", "ofertas", "descuento", "descuentos", "barato", "baratos", "economico", "promocion", "cyber"]):
        ofertas = _BDD.get("ofertas_destacadas", [])
        all_prods = {p["sku"]: p for c in _BDD.get("categorias", []) for p in c.get("productos", [])}
        lines = ["\nOfertas destacadas de la semana:"]
        for o in ofertas:
            prod = all_prods.get(o["sku"])
            if prod:
                lines.append(f"- [{prod.get('categoria','')}] {prod['nombre']}: oferta a ${prod.get('precio_oferta',0):,} pesos ({o['descuento_pct']} por ciento dcto).".replace(",", "."))
        extra_context = "\n".join(lines)

    if extra_context:
        return f"{BASE_SYSTEM_PROMPT}\nCATÁLOGO RELEVANTE PARA ESTA CONSULTA:\n{extra_context}"
    return BASE_SYSTEM_PROMPT


def reload_catalog() -> None:
    global _BDD, _CATEGORIES_BY_ID, _BARCODE_TO_CAT, _SKU_TO_CAT, _BRAND_TO_CATS, _KEYWORD_TO_CATS
    try:
        with open(_BDD_PATH, encoding="utf-8") as _f:
            _BDD = json.load(_f)
        _CATEGORIES_BY_ID = {c["id"]: c for c in _BDD.get("categorias", [])}
        _BARCODE_TO_CAT = {}
        _SKU_TO_CAT = {}
        _BRAND_TO_CATS = {}
        _KEYWORD_TO_CATS = {}

        for cat in _BDD.get("categorias", []):
            cid = cat["id"]
            for prod in cat.get("productos", []):
                cb = str(prod.get("codigo_barra", "")).strip().lower()
                if cb:
                    _BARCODE_TO_CAT[cb] = cid
                sku = str(prod.get("sku", "")).strip().lower()
                if sku:
                    _SKU_TO_CAT[sku] = cid
                marca = str(prod.get("marca", "")).strip().lower()
                if marca:
                    _BRAND_TO_CATS.setdefault(marca, set()).add(cid)
                nombre_words = re.findall(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+', prod.get("nombre", "").lower())
                for w in nombre_words:
                    if len(w) >= 4 and w not in {"para", "negro", "blanco", "azul", "rojo", "gris", "verde", "inch", "pulgadas"}:
                        _KEYWORD_TO_CATS.setdefault(w, set()).add(cid)

        logger.info(f"[LLM] Catálogo BDD cargado desde {_BDD_PATH} ({len(_CATEGORIES_BY_ID)} categorías, {len(_BARCODE_TO_CAT)} barcodes, {len(_BRAND_TO_CATS)} marcas)")
    except Exception as _e:
        _BDD = {}
        _CATEGORIES_BY_ID = {}
        _BARCODE_TO_CAT = {}
        _SKU_TO_CAT = {}
        _BRAND_TO_CATS = {}
        _KEYWORD_TO_CATS = {}
        logger.error(f"[LLM] No se pudo cargar el catálogo BDD: {_e}")

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