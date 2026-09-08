###############################################################################
#  服务器路由 — 统一异常处理的 API 路由
###############################################################################

import os
import re
import json
import random
import numpy as np
import asyncio
from datetime import datetime
from aiohttp import web

from utils.logger import logger


# ─── 路由工具函数 ──────────────────────────────────────────────────────────

def json_ok(data=None):
    """返回成功 JSON 响应"""
    body = {"code": 0, "msg": "ok"}
    if data is not None:
        body["data"] = data
    return web.Response(
        content_type="application/json",
        text=json.dumps(body),
    )


def json_error(msg: str, code: int = -1):
    """返回错误 JSON 响应"""
    return web.Response(
        content_type="application/json",
        text=json.dumps({"code": code, "msg": str(msg)}),
    )


from server.session_manager import session_manager

def get_session(request, sessionid: str):
    """从 app 中获取 session 实例"""
    return session_manager.get_session(sessionid)


async def async_generator_from_sync(sync_gen, *args, **kwargs):
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def run_sync():
        try:
            for item in sync_gen(*args, **kwargs):
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    # Run the synchronous generator in a background thread
    await loop.run_in_executor(None, run_sync)

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


# ─── 路由处理函数 ──────────────────────────────────────────────────────────

async def human(request):
    """文本输入（echo/chat 模式），支持 voice/emotion 参数"""
    try:
        params: dict = await request.json()

        sessionid: str = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")

        if params.get('interrupt'):
            avatar_session.flush_talk()

        datainfo = {}
        if params.get('tts'):  # tts 参数透传（voice, emotion 等）
            datainfo['tts'] = params.get('tts')
        # Pasar el sessionid al LLM para mantener historial de conversación
        datainfo['sessionid'] = sessionid

        if params['type'] == 'echo':
            avatar_session.put_msg_txt(params['text'], datainfo)
            return json_ok()
        elif params['type'] == 'chat':
            llm_response_stream = request.app.get("llm_response_stream")
            if params.get('stream') and llm_response_stream:
                response = web.StreamResponse(
                    status=200,
                    reason='OK',
                    headers={
                        'Content-Type': 'text/event-stream',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive',
                    }
                )
                await response.prepare(request)

                async_gen = async_generator_from_sync(
                    llm_response_stream, params['text'], avatar_session, datainfo
                )

                async for chunk in async_gen:
                    await response.write(chunk.encode('utf-8'))

                await response.write_eof()
                return response
            else:
                llm_response = request.app.get("llm_response")
                if llm_response:
                    loop = asyncio.get_event_loop()
                    response_text = await loop.run_in_executor(
                        None, llm_response, params['text'], avatar_session, datainfo
                    )
                    return json_ok(data={"response": response_text})

        return json_ok()
    except Exception as e:
        logger.exception('human route exception:')
        return json_error(str(e))


async def interrupt_talk(request):
    """打断当前说话"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.flush_talk()
        return json_ok()
    except Exception as e:
        logger.exception('interrupt_talk exception:')
        return json_error(str(e))


async def clear_history(request):
    """Borra el historial de conversación del LLM para la sesión indicada."""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        clear_conv = request.app.get("clear_conversation")
        if clear_conv:
            clear_conv(sessionid)
        return json_ok()
    except Exception as e:
        logger.exception('clear_history exception:')
        return json_error(str(e))


async def humanaudio(request):
    """上传音频文件"""
    try:
        form = await request.post()
        sessionid = str(form.get('sessionid', ''))
        fileobj = form["file"]
        filebytes = fileobj.file.read()

        datainfo = {}

        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.put_audio_file(filebytes, datainfo)
        return json_ok()
    except Exception as e:
        logger.exception('humanaudio exception:')
        return json_error(str(e))


async def set_audiotype(request):
    """设置自定义状态（动作编排）"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.set_custom_state(params['audiotype'])
        return json_ok()
    except Exception as e:
        logger.exception('set_audiotype exception:')
        return json_error(str(e))


async def record(request):
    """录制控制"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        if params['type'] == 'start_record':
            avatar_session.start_recording()
        elif params['type'] == 'end_record':
            avatar_session.stop_recording()
        return json_ok()
    except Exception as e:
        logger.exception('record exception:')
        return json_error(str(e))


async def is_speaking(request):
    """查询是否正在说话"""
    params = await request.json()
    sessionid = params.get('sessionid', '')
    avatar_session = get_session(request, sessionid)
    if avatar_session is None:
        return json_error("session not found")
    return json_ok(data=avatar_session.is_speaking())


async def avatar_general(request):
    """Servir la página avatar-general.html directamente"""
    return web.FileResponse('web/avatar-general.html')


async def avatar_experimental(request):
    """Servir la página avatar-experimental.html directamente"""
    return web.FileResponse('web/avatar-experimental.html')


async def avatar_experimental_pendon(request):
    """Servir la página avatar-experimental-pendon.html directamente"""
    return web.FileResponse('web/avatar-experimental-pendon.html')


async def avatar_experimental_pendon_2(request):
    """Servir la página avatar-experimental-pendon-2.html directamente"""
    return web.FileResponse('web/avatar-experimental-pendon-2.html')


async def get_productos(request):
    """Obtener el catálogo completo y planimetría de productos"""
    try:
        path = 'web/data/bdd.json' if os.path.exists('web/data/bdd.json') else 'data/productos.json'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json_ok(data=data)
    except Exception as e:
        logger.exception('get_productos exception:')
        return json_error(str(e))


async def get_producto_barcode(request):
    """Buscar un producto por código de barras o SKU"""
    raw_code = request.match_info.get('codigo', '')
    codigo = raw_code.strip()
    try:
        path = 'web/data/bdd.json' if os.path.exists('web/data/bdd.json') else 'data/productos.json'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Si es formato bdd.json (por categorías)
        if 'categorias' in data:
            for cat in data.get('categorias', []):
                cat_nombre = cat.get('nombre', '')
                loc = cat.get('ubicacion_tienda', {})
                for prod in cat.get('productos', []):
                    prod_barcode = str(prod.get('codigo_barra', '')).strip()
                    prod_sku = str(prod.get('sku', '')).strip()
                    if prod_barcode == codigo or prod_sku.lower() == codigo.lower():
                        res = dict(prod)
                        res['categoria_nombre'] = cat_nombre
                        res['piso'] = prod.get('piso', loc.get('piso', 1))
                        res['sector'] = loc.get('sector', '')
                        res['pasillo'] = prod.get('pasillo', loc.get('pasillo', ''))
                        res['referencia'] = loc.get('referencia', '')
                        res['oferta'] = 'SI' if prod.get('en_oferta') else 'NO'
                        res['etiquetas'] = prod.get('tags_recomendacion', [])
                        return json_ok(data=res)

        # Si es formato plano (productos.json)
        elif 'productos' in data:
            for prod in data.get('productos', []):
                if str(prod.get('codigo_barra', '')).strip() == codigo:
                    return json_ok(data=prod)

        return json_error("Producto no encontrado", code=404)
    except Exception as e:
        logger.exception('get_producto_barcode exception:')
        return json_error(str(e))


async def get_servipag_servicios(request):
    """Obtener categorías y empresas de servicios disponibles en Servipag"""
    try:
        path = 'web/data/servipag_bdd.json'
        if not os.path.exists(path):
            return json_error("Base de datos Servipag no encontrada", code=404)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json_ok(data=data.get('categorias_servicios', []))
    except Exception as e:
        logger.exception('get_servipag_servicios exception:')
        return json_error(str(e))


async def get_servipag_cuentas(request):
    """Obtener todas las cuentas registradas en Servipag"""
    try:
        path = 'web/data/servipag_bdd.json'
        if not os.path.exists(path):
            return json_error("Base de datos Servipag no encontrada", code=404)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json_ok(data=data.get('cuentas_clientes', []))
    except Exception as e:
        logger.exception('get_servipag_cuentas exception:')
        return json_error(str(e))


async def get_servipag_rut(request):
    """Obtener todas las cuentas asociadas a un RUT con formato y numeración interactiva"""
    from llm import clean_rut, formatear_fecha_natural
    try:
        raw_rut = ''
        if request.method == 'POST':
            try:
                body = await request.json()
                raw_rut = body.get('rut', '')
            except Exception:
                raw_rut = ''
        if not raw_rut:
            raw_rut = request.match_info.get('rut', '')

        target_rut = clean_rut(raw_rut)
        if not target_rut:
            return json_error("Debe proporcionar un RUT válido", code=400)

        path = 'web/data/servipag_bdd.json'
        if not os.path.exists(path):
            return json_error("Base de datos Servipag no encontrada", code=404)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cuentas_raw = data.get('cuentas_clientes', [])
        cuentas = []
        num = 1
        for c in cuentas_raw:
            c_rut = clean_rut(c.get('rut_titular', ''))
            if c_rut == target_rut:
                c_copy = dict(c)
                c_copy['numero'] = num
                num += 1
                monto = c_copy.get('monto', 0)
                c_copy['monto_formateado'] = f"${monto:,}".replace(",", ".")
                estado = str(c_copy.get('estado', '')).lower()
                c_copy['es_vencida'] = (estado == 'vencida')
                c_copy['es_pagada'] = (estado in ('pagada', 'sin_deuda') or monto == 0)
                fecha_v = c_copy.get('fecha_vencimiento')
                c_copy['fecha_vencimiento_natural'] = formatear_fecha_natural(fecha_v) if fecha_v else 'Sin vencimiento'
                cuentas.append(c_copy)

        if not cuentas:
            return json_error(f"No se encontraron cuentas asociadas al RUT {raw_rut}", code=404)

        return json_ok(data={
            "rut": raw_rut,
            "rut_formateado": cuentas[0].get('rut_titular', raw_rut),
            "titular": cuentas[0].get('nombre_titular', ''),
            "total_cuentas": len(cuentas),
            "cuentas": cuentas
        })
    except Exception as e:
        logger.exception('get_servipag_rut exception:')
        return json_error(str(e))


async def servipag_pagar(request):
    """Procesar pago de cuentas Servipag (simulado con persistencia en sesión)"""
    from llm import clean_rut
    try:
        body = await request.json()
        raw_rut = body.get('rut', '')
        cuentas_ids = body.get('cuentas_ids', [])  # Lista de id_cuenta ej: ["CTA-101", "CTA-102"]
        target_rut = clean_rut(raw_rut)

        path = 'web/data/servipag_bdd.json'
        if not os.path.exists(path):
            return json_error("Base de datos Servipag no encontrada", code=404)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cuentas_pagadas = []
        total_pagado = 0

        # Si no enviaron IDs específicos, pagar todas las pendientes del RUT
        for c in data.get('cuentas_clientes', []):
            c_rut = clean_rut(c.get('rut_titular', ''))
            c_id = c.get('id_cuenta')
            if c_rut == target_rut and (not cuentas_ids or c_id in cuentas_ids):
                monto = c.get('monto', 0)
                total_pagado += monto
                # Marcar como pagada en memoria/BDD
                c['estado'] = 'pagada'
                c['monto'] = 0
                c['detalle_estado'] = f"Cuenta pagada exitosamente el {datetime.now().strftime('%d-%m-%Y %H:%M')}"
                cuentas_pagadas.append({
                    "id_cuenta": c_id,
                    "empresa_nombre": c.get('empresa_nombre'),
                    "categoria": c.get('categoria'),
                    "monto_pagado": monto,
                    "monto_formateado": f"${monto:,}".replace(",", ".")
                })

        # Guardar persistencia en servipag_bdd.json
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Recargar catálogo en memoria del LLM
            from llm import reload_catalog
            reload_catalog()
        except Exception as we:
            logger.warning(f"No se pudo escribir en servipag_bdd.json: {we}")

        num_comprobante = f"SP-{random.randint(100000, 999999)}"
        fecha_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        return json_ok(data={
            "comprobante": num_comprobante,
            "fecha": fecha_str,
            "total_pagado": total_pagado,
            "total_formateado": f"${total_pagado:,}".replace(",", "."),
            "cantidad_cuentas": len(cuentas_pagadas),
            "cuentas_pagadas": cuentas_pagadas,
            "mensaje": "Su cuenta ha sido pagada exitosamente."
        })
    except Exception as e:
        logger.exception('servipag_pagar exception:')
        return json_error(str(e))


async def get_servipag_cuenta(request):
    """Buscar una cuenta específica por empresa e identificador"""
    empresa = request.match_info.get('empresa', '').lower().strip()
    identificador = request.match_info.get('identificador', '').strip()
    try:
        path = 'web/data/servipag_bdd.json'
        if not os.path.exists(path):
            return json_error("Base de datos Servipag no encontrada", code=404)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for c in data.get('cuentas_clientes', []):
            emp_id = c.get('empresa_id', '').lower()
            emp_nombre = c.get('empresa_nombre', '').lower()
            c_ident = str(c.get('identificador', '')).strip()
            if (empresa in emp_id or empresa in emp_nombre or emp_id in empresa) and (c_ident.lower() == identificador.lower()):
                return json_ok(data=c)
        return json_error(f"Cuenta no encontrada para empresa '{empresa}' con identificador '{identificador}'", code=404)
    except Exception as e:
        logger.exception('get_servipag_cuenta exception:')
        return json_error(str(e))


async def servipag_verificar(request):
    """Verificar cuenta Servipag con concordancia de empresa, RUT e identificador (anti-alucinación)"""
    from llm import verificar_cuenta_servipag, normalize_user_input
    try:
        if request.method == 'POST':
            data = await request.json()
        else:
            data = dict(request.query)

        empresa = data.get('empresa', '').strip() or None
        rut = data.get('rut', '').strip() or None
        identificador = data.get('identificador', '').strip() or None
        categoria = data.get('categoria', '').strip() or None

        if rut:
            rut = normalize_user_input(rut)

        if not (empresa or rut or identificador or categoria):
            return json_error("Debe proporcionar al menos 'empresa', 'rut' o 'identificador'", code=400)

        resultado = verificar_cuenta_servipag(empresa=empresa, rut=rut, identificador=identificador, categoria=categoria)
        if resultado is None:
            return json_error("No se encontraron registros para la consulta", code=404)

        return json_ok(data=resultado)
    except Exception as e:
        logger.exception('servipag_verificar exception:')
        return json_error(str(e))


# ─── 路由注册 ──────────────────────────────────────────────────────────────

def setup_routes(app):
    """注册所有路由到 aiohttp app"""
    app.router.add_post("/human", human)
    app.router.add_post("/humanaudio", humanaudio)
    app.router.add_post("/set_audiotype", set_audiotype)
    app.router.add_post("/record", record)
    app.router.add_post("/interrupt_talk", interrupt_talk)
    app.router.add_post("/is_speaking", is_speaking)
    app.router.add_post("/clear_history", clear_history)
    app.router.add_get("/api/productos", get_productos)
    app.router.add_get("/api/producto/barcode/{codigo}", get_producto_barcode)
    app.router.add_get("/api/servipag/servicios", get_servipag_servicios)
    app.router.add_get("/api/servipag/cuentas", get_servipag_cuentas)
    app.router.add_get("/api/servipag/rut/{rut}", get_servipag_rut)
    app.router.add_post("/api/servipag/rut", get_servipag_rut)
    app.router.add_post("/api/servipag/pagar", servipag_pagar)
    app.router.add_get("/api/servipag/cuenta/{empresa}/{identificador}", get_servipag_cuenta)
    app.router.add_post("/api/servipag/verificar", servipag_verificar)
    app.router.add_get("/api/servipag/verificar", servipag_verificar)
    app.router.add_get("/avatar-general", avatar_general)
    app.router.add_get("/avatar-experimental", avatar_experimental)
    app.router.add_get("/avatar-experimental-pendon", avatar_experimental_pendon)
    app.router.add_get("/avatar-experimental-pendon-2", avatar_experimental_pendon_2)
    app.router.add_static('/', path='web')
