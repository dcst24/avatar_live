###############################################################################
#  服务器路由 — 统一异常处理的 API 路由
###############################################################################

import os
import json
import numpy as np
import asyncio
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

    # Ejecutar en segundo plano de manera concurrente para que los tokens hagan stream de inmediato
    fut = loop.run_in_executor(None, run_sync)

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        if fut.done() and not fut.cancelled():
            _ = fut.exception()


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
            abort_gen = request.app.get("abort_generation")
            if abort_gen and sessionid:
                abort_gen(sessionid)
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

                try:
                    async for chunk in async_gen:
                        await response.write(chunk.encode('utf-8'))
                    await response.write_eof()
                except (asyncio.CancelledError, ConnectionResetError, Exception) as stream_err:
                    logger.info(f"[Routes] Streaming SSE cerrado/cancelado para sesión {sessionid}: {type(stream_err).__name__}")
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
        abort_gen = request.app.get("abort_generation")
        if abort_gen and sessionid:
            abort_gen(sessionid)
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


async def get_gym_data(request):
    """Obtener información completa de FitLife Gym, planes y bancos"""
    try:
        path = 'web/data/gym_data.json' if os.path.exists('web/data/gym_data.json') else 'data/gym_data.json'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json_ok(data=data)
    except Exception as e:
        logger.exception('get_gym_data exception:')
        return json_error(str(e))


async def get_gym_cliente(request):
    """Buscar o auto-generar datos de cliente por RUT"""
    raw_rut = request.match_info.get('rut', '').strip()
    clean_rut = raw_rut.replace('.', '').replace('-', '').upper()
    try:
        path = 'web/data/gym_data.json' if os.path.exists('web/data/gym_data.json') else 'data/gym_data.json'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for c in data.get('clientes_demo', []):
            if c.get('rut_limpio', '').upper() == clean_rut or c.get('rut', '').replace('.', '').replace('-', '').upper() == clean_rut:
                return json_ok(data=c)

        # Si no existe en demo, generar cliente nuevo válido
        formatted_rut = raw_rut
        if len(clean_rut) >= 8:
            cuerpo = clean_rut[:-1]
            dv = clean_rut[-1]
            try:
                cuerpo_fmt = f"{int(cuerpo):,}".replace(',', '.')
                formatted_rut = f"{cuerpo_fmt}-{dv}"
            except Exception:
                formatted_rut = f"{cuerpo}-{dv}"

        nuevo_cliente = {
            "rut": formatted_rut,
            "rut_limpio": clean_rut,
            "nombre": "Socio Gimnasio",
            "email": f"socio.{clean_rut.lower()}@fitlife-gym.cl",
            "telefono": "+56 9 9000 1234",
            "estado": "Nuevo Socio"
        }
        return json_ok(data=nuevo_cliente)
    except Exception as e:
        logger.exception('get_gym_cliente exception:')
        return json_error(str(e))


async def post_simular_pago(request):
    """Simular transacción de pago POS / Webpay para FitLife Gym con cuotas"""
    try:
        import datetime
        import random

        params = await request.json()
        plan_id = params.get('plan_id', 'plan_1m')
        banco_id = params.get('banco_id', 'santander')
        rut = params.get('rut', '12.345.678-5')
        cliente_nombre = params.get('nombre', 'Socio FitLife')
        cliente_email = params.get('email', 'cliente@correo.cl')
        cuotas_solicitadas = int(params.get('cuotas', 1))

        if cuotas_solicitadas not in [1, 3, 6, 12]:
            cuotas = 1
        else:
            cuotas = cuotas_solicitadas

        path = 'web/data/gym_data.json' if os.path.exists('web/data/gym_data.json') else 'data/gym_data.json'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Buscar plan
        plan = next((p for p in data.get('planes', []) if p['id'] == plan_id), None)
        if not plan:
            plan = data.get('planes', [])[0]

        # Buscar banco
        banco = next((b for b in data.get('bancos', []) if b['id'] == banco_id), None)
        banco_nombre = banco['nombre'] if banco else "Banco Santander"
        es_santander = "santander" in banco_id.lower()

        monto_original = plan.get('precio', 34990)
        descuento = int(monto_original * 0.20) if es_santander else 0
        monto_pagado = monto_original - descuento
        monto_cuota = int(round(monto_pagado / cuotas))

        if cuotas == 1:
            texto_cuotas = "1 Pago (Contado)"
        elif cuotas in [3, 6] or (cuotas == 12 and es_santander):
            texto_cuotas = f"{cuotas} Cuotas Sin Interés ({cuotas}x ${monto_cuota:,})".replace(',', '.')
        else:
            texto_cuotas = f"{cuotas} Cuotas ({cuotas}x ${monto_cuota:,})".replace(',', '.')

        now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        op_num = f"OP-{random.randint(100000, 999999)}"
        auth_code = f"AUTH-{random.randint(10000, 99999)}"

        comprobante = {
            "codigo_operacion": op_num,
            "codigo_autorizacion": auth_code,
            "estado": "APROBADO",
            "mensaje": "Transacción aprobada exitosamente",
            "plan": {
                "id": plan["id"],
                "nombre": plan["nombre"],
                "meses": plan["meses"]
            },
            "cliente": {
                "rut": rut,
                "nombre": cliente_nombre,
                "email": cliente_email
            },
            "banco": banco_nombre,
            "es_santander": es_santander,
            "monto_original": monto_original,
            "descuento": descuento,
            "monto_pagado": monto_pagado,
            "cuotas": cuotas,
            "monto_cuota": monto_cuota,
            "texto_cuotas": texto_cuotas,
            "fecha": now_str,
            "email_comprobante": cliente_email
        }
        logger.info(f"[Pago Simulado] Plan: {plan['nombre']} | Cuotas: {texto_cuotas} | RUT: {rut} | Banco: {banco_nombre} | Monto: ${monto_pagado:,}")
        return json_ok(data=comprobante)
    except Exception as e:
        logger.exception('post_simular_pago exception:')
        return json_error(str(e))


async def get_pos_ports(request):
    """Retorna los puertos COM / Serial disponibles en el sistema para conectar el POS Getnet"""
    import platform
    import glob
    ports = []
    try:
        if platform.system() == "Windows":
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
                for i in range(128):
                    try:
                        val_name, port_name, _ = winreg.EnumValue(key, i)
                        ports.append({
                            "port": port_name,
                            "device": val_name,
                            "description": f"Puerto Serial {port_name} ({val_name.split(chr(92))[-1]})"
                        })
                    except OSError:
                        break
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
        else:
            # Linux / macOS / Jetson
            device_paths = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyS*')
            for path in sorted(device_paths):
                ports.append({
                    "port": path,
                    "device": path,
                    "description": f"Puerto Serial {path}"
                })
        return json_ok(data={"ports": ports, "count": len(ports)})
    except Exception as e:
        logger.exception("Error listando puertos seriales:")
        return json_error(str(e))


async def post_registrar_pago_real(request):
    """Registra una transacción confirmada y aprobada por el terminal físico POS Getnet"""
    try:
        body = await request.json()
        plan_id = body.get('plan_id', 'plan_1m')
        banco_nombre = body.get('banco', 'Banco Santander')
        es_santander = body.get('es_santander', False)
        cuotas = int(body.get('cuotas', 1))
        monto_pagado = int(body.get('monto_pagado', 0))
        monto_original = int(body.get('monto_original', monto_pagado))
        descuento = int(body.get('descuento', 0))
        rut = body.get('rut', '12.345.678-5')
        cliente_nombre = body.get('nombre', 'Socio FitLife')
        cliente_email = body.get('email', 'cliente@correo.cl')
        auth_code = body.get('codigo_autorizacion') or f"GET-{random.randint(100000, 999999)}"
        op_num = body.get('codigo_operacion') or f"OP-{random.randint(100000, 999999)}"
        card_number = body.get('card_number', '**** **** **** ****')
        card_brand = body.get('card_brand', 'TRANSACCIÓN POS')

        data = load_gym_data()
        plan = next((p for p in data.get('planes', []) if p['id'] == plan_id), None)
        if not plan:
            plan = {"id": plan_id, "nombre": body.get('plan_nombre', 'Plan Gym'), "meses": 1}

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if cuotas == 1:
            texto_cuotas = "1 Pago (Contado)"
            monto_cuota = monto_pagado
        elif cuotas in (3, 6) or (cuotas == 12 and es_santander):
            texto_cuotas = f"{cuotas} Cuotas Sin Interés"
            monto_cuota = round(monto_pagado / cuotas)
        else:
            texto_cuotas = f"{cuotas} Cuotas"
            monto_cuota = round(monto_pagado / cuotas)

        comprobante = {
            "codigo_operacion": str(op_num),
            "codigo_autorizacion": str(auth_code),
            "estado": "APROBADO",
            "mensaje": "Transacción aprobada exitosamente por POS Getnet",
            "origen": "GETNET_POS_REAL",
            "card_number": card_number,
            "card_brand": card_brand,
            "plan": {
                "id": plan["id"],
                "nombre": plan["nombre"],
                "meses": plan.get("meses", 1)
            },
            "cliente": {
                "rut": rut,
                "nombre": cliente_nombre,
                "email": cliente_email
            },
            "banco": banco_nombre,
            "es_santander": es_santander,
            "monto_original": monto_original,
            "descuento": descuento,
            "monto_pagado": monto_pagado,
            "cuotas": cuotas,
            "monto_cuota": monto_cuota,
            "texto_cuotas": texto_cuotas,
            "fecha": now_str,
            "email_comprobante": cliente_email
        }
        logger.info(f"[Pago Real POS Getnet] Auth: {auth_code} | Op: {op_num} | Plan: {plan['nombre']} | Cuotas: {texto_cuotas} | Monto: ${monto_pagado:,} | RUT: {rut}")
        return json_ok(data=comprobante)
    except Exception as e:
        logger.exception('post_registrar_pago_real exception:')
        return json_error(str(e))


async def favicon(request):
    return aiohttp.web.Response(status=204)


# ─── 路由注册 ──────────────────────────────────────────────────────────────

def setup_routes(app):
    """注册所有路由到 aiohttp app"""
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_post("/human", human)
    app.router.add_post("/humanaudio", humanaudio)
    app.router.add_post("/set_audiotype", set_audiotype)
    app.router.add_post("/record", record)
    app.router.add_post("/interrupt_talk", interrupt_talk)
    app.router.add_post("/is_speaking", is_speaking)
    app.router.add_post("/clear_history", clear_history)
    app.router.add_get("/api/gym/data", get_gym_data)
    app.router.add_get("/api/gym/planes", get_gym_data)
    app.router.add_get("/api/gym/cliente/{rut}", get_gym_cliente)
    app.router.add_post("/api/gym/pago/simular", post_simular_pago)
    app.router.add_post("/api/gym/pago/registrar", post_registrar_pago_real)
    app.router.add_get("/api/pos/ports", get_pos_ports)
    app.router.add_get("/avatar-general", avatar_general)
    app.router.add_get("/avatar-experimental", avatar_experimental)
    app.router.add_get("/avatar-experimental-pendon", avatar_experimental_pendon)
    app.router.add_get("/avatar-experimental-pendon-2", avatar_experimental_pendon_2)
    app.router.add_static('/getnet', path='getnet')
    app.router.add_static('/', path='web')




