import os
import json
import time
import random
import hashlib
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

try:
    import serial
    import serial.tools.list_ports
    HAS_PYSERIAL = True
except ImportError:
    HAS_PYSERIAL = False

from utils.logger import logger

class PosGetnetManager:
    """
    Gestor del terminal físico POS Getnet vía conexión Serial local en el servidor Python.
    Mantiene la conexión permanentemente abierta y ofrece respaldo simulado automático
    cuando no hay un terminal físico conectado.
    """

    def __init__(self, baudrate: int = 115200):
        self.baudrate = baudrate
        self.ser: Optional[Any] = None
        self.port_name: Optional[str] = None
        self.is_connected = False
        self.mode = "simulated"  # 'real' o 'simulated'
        self.lock = threading.Lock()
        
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._rx_buffer = ""
        
        # Futuro / evento para transacciones activas
        self._active_future: Optional[asyncio.Future] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_poll_time = 0

    def start(self, preferred_port: Optional[str] = None):
        """Inicia el servicio y busca el terminal físico en segundo plano"""
        self._running = True
        threading.Thread(target=self._auto_connect_loop, args=(preferred_port,), daemon=True).start()

    def stop(self):
        """Cierra la conexión serial de forma limpia"""
        self._running = False
        self.disconnect()

    def disconnect(self):
        with self.lock:
            if self.ser:
                try:
                    self.ser.close()
                except Exception as e:
                    logger.debug(f"[POS Getnet] Error al cerrar puerto: {e}")
                self.ser = None
            self.is_connected = False
            self.mode = "simulated"

    def _auto_connect_loop(self, preferred_port: Optional[str] = None):
        """Hilo de auto-conexión y reconexión"""
        while self._running:
            if not self.is_connected:
                success = self.connect_port(preferred_port)
                if not success and preferred_port:
                    # Si falló el preferido, intentar con cualquier otro
                    self.connect_port(None)
            time.sleep(5)

    def list_serial_ports(self):
        """Devuelve los puertos seriales disponibles en el sistema operativo"""
        if not HAS_PYSERIAL:
            return []
        results = []
        for p in serial.tools.list_ports.comports():
            results.append({
                "port": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "vid": hex(p.vid) if p.vid else None,
                "pid": hex(p.pid) if p.pid else None
            })
        return results

    def connect_port(self, port_name: Optional[str] = None) -> bool:
        """Intenta abrir y verificar el puerto serial con el POS Getnet"""
        if not HAS_PYSERIAL:
            self.mode = "simulated"
            return False

        ports_to_try = [port_name] if port_name else [p.device for p in serial.tools.list_ports.comports()]
        
        for port in ports_to_try:
            if not port:
                continue
            try:
                # Intentar abrir puerto
                ser = serial.Serial(
                    port=port,
                    baudrate=self.baudrate,
                    timeout=0.6,
                    write_timeout=1.0,
                    rtscts=False,
                    dsrdtr=False
                )
                try:
                    ser.dtr = True
                    ser.rts = True
                except Exception:
                    pass

                # Enviar wakeup y sondeo Poll (Command 106)
                poll_payload = {
                    "Command": 106,
                    "DateTime": datetime.now().isoformat()
                }
                msg = self._sign_message(poll_payload)
                ser.write(b"\r\n")
                time.sleep(0.05)
                ser.write(msg.encode('utf-8'))

                # Esperar respuesta
                response = ser.read(512).decode('utf-8', errors='ignore')
                ser.close()

                if "{" in response and ("106" in response or "ResponseCode" in response or "Received" in response):
                    # ¡Puerto verificado! Abrir conexión permanente
                    with self.lock:
                        self.ser = serial.Serial(
                            port=port,
                            baudrate=self.baudrate,
                            timeout=0.2,
                            write_timeout=2.0
                        )
                        try:
                            self.ser.dtr = True
                            self.ser.rts = True
                        except Exception:
                            pass
                        self.port_name = port
                        self.is_connected = True
                        self.mode = "real"
                        self._rx_buffer = ""
                        self._last_poll_time = time.time()
                        
                        logger.info(f"[POS Getnet] Conectado exitosamente en terminal físico: {port}")
                        
                        # Iniciar hilo de lectura continua
                        if not self._read_thread or not self._read_thread.is_alive():
                            self._read_thread = threading.Thread(target=self._serial_reader_loop, daemon=True)
                            self._read_thread.start()
                        return True
            except Exception as e:
                logger.debug(f"[POS Getnet] Sondeo en puerto {port} falló: {e}")
                continue

        # Si ningún puerto físico respondió, quedar en modo simulado listo para operar
        self.mode = "simulated"
        return False

    def _sign_message(self, data_dict: dict) -> str:
        """Firma el JSON con SHA-256 según protocolo Getnet POS"""
        json_str = json.dumps(data_dict, separators=(',', ':'))
        sign = hashlib.sha256(json_str.encode('utf-8')).hexdigest().upper()
        envelope = {
            "JsonSerialized": json_str,
            "Sign": sign
        }
        return json.dumps(envelope, separators=(',', ':')) + "\r\n"

    def _serial_reader_loop(self):
        """Bucle de lectura continua del puerto serial físico"""
        logger.info("[POS Getnet] Lector serial iniciado en background.")
        while self._running and self.is_connected and self.ser:
            try:
                raw = self.ser.read(256)
                if raw:
                    self._rx_buffer += raw.decode('utf-8', errors='ignore')
                    self._process_rx_buffer()
            except Exception as e:
                logger.warn(f"[POS Getnet] Error en lectura serial: {e}")
                time.sleep(0.5)
                # Si el error persiste y el puerto no está abierto, desconectar
                if not self.ser or not self.ser.is_open:
                    self.disconnect()
                    break
        logger.info("[POS Getnet] Lector serial detenido.")

    def _process_rx_buffer(self):
        """Extrae y parsea paquetes JSON delimitados por llaves { ... }"""
        str_buf = self._rx_buffer
        if "{" not in str_buf:
            return

        while True:
            start = str_buf.find("{")
            if start == -1:
                self._rx_buffer = ""
                break
            
            depth = 0
            end = -1
            for i in range(start, len(str_buf)):
                if str_buf[i] == "{":
                    depth += 1
                elif str_buf[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            
            if end != -1:
                json_candidate = str_buf[start:end+1]
                str_buf = str_buf[end+1:]
                self._rx_buffer = str_buf
                try:
                    parsed = json.loads(json_candidate)
                    if "JsonSerialized" in parsed and isinstance(parsed["JsonSerialized"], str):
                        try:
                            inner = json.loads(parsed["JsonSerialized"])
                            parsed.update(inner)
                        except Exception:
                            pass
                    self._handle_pos_message(parsed)
                except Exception as e:
                    logger.debug(f"[POS Getnet] Error parseando JSON: {e}")
            else:
                self._rx_buffer = str_buf
                break

    def _handle_pos_message(self, msg: dict):
        """Procesa una respuesta recibida del POS físico"""
        logger.info(f"[POS Getnet RX]: {msg}")
        
        # Notificar al futuro activo si corresponde
        if self._active_future and not self._active_future.done():
            # Si es confirmación final de venta (Command 100 o ResponseCode presente)
            if msg.get("Command") == 100 or "ResponseCode" in msg:
                if self._loop:
                    self._loop.call_soon_threadsafe(self._active_future.set_result, msg)
            elif msg.get("Command") == 116: # Cancelación
                if self._loop:
                    self._loop.call_soon_threadsafe(self._active_future.set_result, msg)

    async def execute_sale(self, amount: int, ticket: Optional[str] = None, timeout: int = 180) -> Dict[str, Any]:
        """
        Ejecuta una venta en el terminal POS Getnet.
        Si está en modo 'simulated', emula el flujo tras 3 segundos.
        """
        ticket = ticket or f"{random.randint(100000, 999999)}"
        self._loop = asyncio.get_event_loop()

        # Si está en modo simulado:
        if self.mode == "simulated" or not self.is_connected or not self.ser:
            logger.info(f"[POS Getnet Simulator] Procesando cobro simulado por ${amount:,} CLP...")
            await asyncio.sleep(2.8)
            return {
                "Command": 100,
                "ResponseCode": 0,
                "ResponseMessage": "Transacción Aprobada (Simulación Getnet)",
                "Amount": amount,
                "AuthorizationCode": f"{random.randint(100000, 999999)}",
                "OperationNumber": f"OP-{random.randint(1000, 9999)}",
                "CardNumber": "4111********1111",
                "CardBrand": "VISA DEBITO",
                "Ticket": ticket,
                "SharesNumber": 1,
                "IsSimulated": True
            }

        # Modo Físico Real:
        self._active_future = self._loop.create_future()
        sale_data = {
            "Command": 100,
            "Amount": amount,
            "Ticket": ticket,
            "DateTime": datetime.now().isoformat()
        }
        msg = self._sign_message(sale_data)

        try:
            with self.lock:
                # Wakeup
                self.ser.write(b"\r\n")
                time.sleep(0.04)
                self.ser.write(msg.encode('utf-8'))
                logger.info(f"[POS Getnet TX Venta]: ${amount} | Ticket: {ticket}")

            # Esperar respuesta del terminal hasta el timeout
            result = await asyncio.wait_for(self._active_future, timeout=float(timeout))
            return result
        except asyncio.TimeoutError:
            logger.warn(f"[POS Getnet] Timeout de {timeout}s esperando respuesta del POS.")
            return {
                "Command": 100,
                "ResponseCode": 998,
                "ResponseMessage": "Tiempo de espera agotado en terminal POS",
                "Amount": amount,
                "IsSimulated": False
            }
        finally:
            self._active_future = None

    async def cancel_sale(self) -> Dict[str, Any]:
        """Envía cancelación de venta activa"""
        if self.mode == "simulated" or not self.is_connected or not self.ser:
            if self._active_future and not self._active_future.done():
                self._active_future.set_result({
                    "Command": 116,
                    "ResponseCode": 999,
                    "ResponseMessage": "Venta Cancelada por el Usuario"
                })
            return {"code": 0, "msg": "Venta simulada cancelada"}

        cancel_data = {
            "Command": 116,
            "DateTime": datetime.now().isoformat()
        }
        msg = self._sign_message(cancel_data)
        try:
            with self.lock:
                self.ser.write(msg.encode('utf-8'))
            return {"code": 0, "msg": "Comando de cancelación enviado al POS"}
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado de conexión del POS"""
        return {
            "connected": self.is_connected,
            "mode": self.mode,
            "port": self.port_name,
            "baudrate": self.baudrate,
            "available_ports": self.list_serial_ports()
        }

# Instancia singleton para la aplicación
pos_manager = PosGetnetManager()
