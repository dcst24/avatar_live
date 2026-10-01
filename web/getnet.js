/*!
 * Libreria Getnet
 * Version: 1.5.9 (Restaurado desde version funcional + fix cuotas + fix autoConnect)
 * Fecha: 2026-10-01
 */
(function(root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        const exports = factory();
        root.Getnet = exports.Getnet;
        root.POSCommands = exports.POSCommands;
    }
})(typeof self !== 'undefined' ? self : typeof window !== 'undefined' ? window : this, function() {
    let SerialCom = null;
    let WebSerialCom = null;
    let Callback = (msg) => { console.log("[Getnet Callback]", msg); };
    let textoCallback = "";
    let LogCallback = (log) => { console.log("[Getnet Log]", log); };
    var serialComFijo = "";
    var TimeoutForResponse = null;
    var defaultReceivedTimeout = 60;
    var ReceivedTimeout = null;
    var defaultTimeout = 180;
    var defaultMinTimeout = 15;
    var defaultMaxTimeout = 180;
    var errorCallback = (err) => { console.warn("[Getnet Timeout/Error]", err); };
    var isWebSerial = false;
    var isAgentePos = false;

    class POSCommands {
        static Function = {
            Sale: 100,
            LastVoucher: 101,
            Refund: 102,
            Close: 103,
            Totals: 104,
            Details: 105,
            Poll: 106,
            SetNormalMode: 107,
            Return: 108,
            DuplicateOthers: 109,
            SalesBySeller: 110,
            TipReport: 111,
            AlternativeSaleExemptedAffects: 112,
            DefaultSaleType: 113,
            ParameterReport: 114,
            SimReport: 115,
            CancelSale: 116,
        };
        static SaleType = {
            Sale: 0,
            SaleAffects: 1,
            InvoiceAffects: 2,
            SaleExempted: 3,
            InvoiceExempted: 4,
            CollectionAffects: 5,
            CollectionExempted: 6,
        };
    }

    class WebSerial {
        constructor() {
            this.socket = new WebSocket("ws://localhost:8000/");
            this.resolveSetPort = null;
            this.port = "";
            this.waitingPort = false;
            this.lastCommand = new Date();
            this.espera = 250;
            this.queue = [];
            this.socket.onmessage = function (event) {
                try {
                    const jsonData = JSON.parse(event.data);
                    MensajeRecibido(jsonData);
                } catch { }
            };
            this.socket.onerror = (error) => {
                console.error("Error en WebSocket POS Agent", error);
            };
        }
        async getPorts() {
            return new Promise(async (resolve, reject) => {
                try {
                    if (serialComFijo) {
                        this.setPort(serialComFijo);
                        resolve();
                    }
                    this.waitingPort = true;
                    this.socket.onopen = () => {
                        this.send(JSON.stringify({ Type: "ports" }));
                        resolve();
                    };
                } catch (error) {
                    console.error("No se selecciono el puerto", error);
                    reject(error);
                }
            });
        }
        setPort(port = "") {
            this.port = port;
            this.waitingPort = false;
            this.enqueueMessage({
                Type: "open",
                OpenParams: { Port: this.port, BaudRate: 115200 },
                WriteParams: null
            });
            this.processQueue();
        }
        useGetnetPosAgent() {
            this.enqueueMessage({ Type: "getnet-port", OpenParams: { Port: this.port, BaudRate: 115200 }, WriteParams: null });
            this.processQueue();
        }
        enqueueMessage(mensaje) {
            this.queue.push(mensaje);
        }
        async write(mensaje) {
            this.enqueueMessage({ Type: "write", WriteParams: { Message: mensaje } });
            this.processQueue();
        }
        async processQueue() {
            if (this.socket.readyState == this.socket.OPEN) {
                if (this.queue.length === 0) { return; }
                const mensaje = this.queue.shift();
                await this.processMessage(mensaje);
                this.processQueue();
            } else {
                await gSleep(250);
                this.processQueue();
            }
        }
        processMessage(mensaje) {
            return new Promise(async (resolve) => {
                while (!this.canProcess()) { await this.esperarProceso(); }
                this.lastCommand = new Date();
                this.socket.send(JSON.stringify(mensaje));
                resolve();
            });
        }
        send(mensaje) {
            try { this.socket.send(mensaje); } catch (error) { console.log(error); }
        }
        canProcess() {
            if (this.waitingPort) return false;
            if (new Date() - this.lastCommand >= this.espera) return true;
            return false;
        }
        esperarProceso() {
            return new Promise(res => setTimeout(res, Math.max(10, this.espera - (new Date() - this.lastCommand))));
        }
    }

    class Serial {
        port = null;
        reader = null;
        text = "";
        lastCommand = new Date(0);
        espera = 150;
        baudRate = 115200;
        isReading = false;
        openedAt = 0;

        async setPort(portInstance = null, baudRate = 115200) {
            this.baudRate = baudRate || 115200;
            try {
                let targetPort = portInstance;
                if (!targetPort && navigator && navigator.serial) {
                    targetPort = await navigator.serial.requestPort();
                }
                if (!targetPort) { throw new Error("No se selecciono ningun puerto COM."); }
                if (this.port && this.port !== targetPort) { await this.disconnect(); }
                this.port = targetPort;
                this.text = "";
                this.openedAt = Date.now();
                await this.openPort();
                this.startReading();
                return this.port;
            } catch (error) {
                console.error("[Getnet POS] Error configurando puerto COM:", error);
                throw error;
            }
        }

        clearBuffer() { this.text = ""; }

        async openPort() {
            if (this.port) {
                if (!this.port.readable || !this.port.writable) {
                    try {
                        await this.port.open({ baudRate: this.baudRate });
                        console.log("[Getnet POS] Puerto COM abierto a " + this.baudRate + " baud");
                    } catch (err) {
                        if (err.message && err.message.includes('already open')) { return; }
                        throw err;
                    }
                }
            }
        }

        startReading() {
            if (!this.port || !this.port.readable || this.isReading) return;
            this.isReading = true;
            this.readLoop();
        }

        async readLoop() {
            const textDecoder = new TextDecoder();
            console.log('[Getnet POS] readLoop iniciado.');
            while (this.isReading && this.port && this.port.readable) {
                try {
                    this.reader = this.port.readable.getReader();
                    while (true) {
                        const { value, done } = await this.reader.read();
                        if (done) {
                            console.warn('[Getnet POS] Stream serial cerrado (done=true). Puerto fisicamente desconectado.');
                            break;
                        }
                        if (value) {
                            if (this.openedAt && (Date.now() - this.openedAt < 400)) {
                                this.text = "";
                                continue;
                            }
                            this.text += textDecoder.decode(value, { stream: true });
                            this.processBuffer();
                        }
                    }
                } catch (readErr) {
                    // NO usar break aqui: si el error es transitorio, el loop se recupera solo.
                    // Solo salir si el puerto fue cerrado intencionalmente (isReading=false).
                    console.warn('[Getnet POS] readLoop error (se intentara recuperar):', readErr.message || readErr);
                } finally {
                    if (this.reader) {
                        try { this.reader.releaseLock(); } catch (_) {}
                        this.reader = null;
                    }
                }
                if (!this.isReading || !this.port || !this.port.readable) break;
                // Pausa breve antes de reintentar adquirir el reader
                await new Promise(r => setTimeout(r, 200));
            }
            this.isReading = false;
            console.log('[Getnet POS] readLoop terminado.');
        }

        processBuffer() {
            let str = this.text;
            if (!str || str.indexOf('{') === -1) return;
            while (true) {
                const start = str.indexOf('{');
                if (start === -1) { str = ""; break; }
                let depth = 0, end = -1;
                for (let i = start; i < str.length; i++) {
                    if (str[i] === '{') depth++;
                    else if (str[i] === '}') { depth--; if (depth === 0) { end = i; break; } }
                }
                if (end === -1) { if (start > 0) { str = str.slice(start); } break; }
                const jsonCandidate = str.slice(start, end + 1);
                str = str.slice(end + 1);
                try {
                    const parsed = JSON.parse(jsonCandidate);
                    // PROTOCOLO OFICIAL GETNET: Si el mensaje del POS no es un ACK (Received==undefined),
                    // responder de inmediato con { Received: true } para que el POS no se bloquee.
                    if (parsed.Received === undefined) {
                        this.send(JSON.stringify({ Received: true })).catch(e => console.warn("[Getnet POS] Error enviando ACK:", e));
                    }
                    MensajeRecibido(parsed);
                } catch (e) {
                    console.warn("[Getnet POS] JSON malformado:", e);
                }
            }
            this.text = str;
        }

        async write(jsonSerialized) {
            try {
                // Si el readLoop murio (por ejemplo tras un error de lectura), reiniciarlo
                if (this.port && this.port.readable && !this.isReading) {
                    console.warn('[Getnet POS] readLoop inactivo detectado antes de write. Reiniciando...');
                    this.startReading();
                }
                while (!this.canProcess()) { await this.esperarProceso(); }
                await this.send(jsonSerialized);
            } catch (error) {
                console.error('[Getnet POS] Error en write:', error);
                throw error;
            }
        }

        async send(dataString) {
            if (!this.port || !this.port.writable) {
                throw new Error("El puerto POS Getnet no esta abierto para escritura");
            }
            if (!this.writeQueue) this.writeQueue = Promise.resolve();
            this.writeQueue = this.writeQueue.catch(() => {}).then(async () => {
                let writer = null;
                try {
                    writer = this.port.writable.getWriter();
                    // PROTOCOLO SERIAL POS: Toda trama enviada DEBE terminar en \r\n (CRLF).
                    // Sin el delimitador \r\n, el parser UART del terminal POS no detecta el fin de trama
                    // y retiene el comando en el buffer hasta la llegada del siguiente mensaje.
                    const payload = (dataString.endsWith('\r\n') ? dataString : (dataString.endsWith('\n') ? dataString.slice(0, -1) + '\r\n' : dataString + '\r\n'));
                    const bytes = new TextEncoder().encode(payload);
                    this.lastCommand = new Date();
                    await writer.write(bytes);
                } catch (err) {
                    console.error('[Getnet POS] Error en stream writer:', err);
                    throw err;
                } finally {
                    if (writer) {
                        try { writer.releaseLock(); } catch (_) {}
                    }
                }
            });
            return this.writeQueue;
        }

        canProcess() { return (new Date() - this.lastCommand) >= this.espera; }

        esperarProceso() {
            return new Promise(res => setTimeout(res, Math.max(10, this.espera - (new Date() - this.lastCommand))));
        }

        async disconnect() {
            this.isReading = false;
            if (this.reader) {
                try { await this.reader.cancel(); } catch (_) {}
                try { this.reader.releaseLock(); } catch (_) {}
                this.reader = null;
            }
            if (this.port) {
                try { await this.port.close(); } catch (_) {}
                this.port = null;
            }
            this.text = "";
            console.log("[Getnet POS] Puerto desconectado limpiamente.");
        }
    }

    async function connectWebSerial() {
        return new Promise((resolve) => {
            if (WebSerialCom) WebSerialCom.setPort("");
            resolve();
        });
    }

    async function WebSerialComunication(jsonSerialized) {
        if (!WebSerialCom && !isAgentePos) { WebSerialCom = new WebSerial(); }
        await connectWebSerial();
        if (WebSerialCom) WebSerialCom.write(jsonSerialized);
    }

    // RESTAURADO al original funcional: si no hay conexion, pide puerto al usuario
    async function SerialComunication(jsonSerialized) {
        if (getIsWebSerialCommunication()) { await WebSerialComunication(jsonSerialized); return; }
        if (!SerialCom || !SerialCom.port) {
            SerialCom = new Serial();
            await SerialCom.setPort();
        }
        await SerialCom.write(jsonSerialized);
    }

    function getIsWebSerialCommunication() {
        return (typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes("Firefox")) || isWebSerial;
    }

    function SignMessage(data) {
        return new Promise(async (resolve, reject) => {
            try {
                var jsonSerialized = JSON.stringify(data);
                var sign = await SignWithSha256(jsonSerialized);
                resolve(JSON.stringify({ JsonSerialized: jsonSerialized, Sign: sign.toUpperCase() }));
            } catch (error) { reject(error); }
        });
    }

    function SignWithSha256(jsonSerialized) {
        return new Promise(async (resolve, reject) => {
            try {
                const hashArray = await hashJsonSerialized(jsonSerialized);
                resolve(hashArray.map((b) => b.toString(16).padStart(2, "0")).join(""));
            } catch (error) { reject(error); }
        });
    }

    async function hashJsonSerialized(jsonSerialized) {
        return new Promise(async (resolve) => {
            try {
                if (typeof CryptoJS !== 'undefined' && CryptoJS.SHA256) {
                    resolve(hashWithCryptoJs(jsonSerialized)); return;
                }
            } catch (_) {}
            try {
                const encoder = new TextEncoder();
                const data = encoder.encode(jsonSerialized);
                const hash = await window.crypto.subtle.digest("SHA-256", data);
                resolve(Array.from(new Uint8Array(hash)));
            } catch (err) {
                console.error("Error al calcular hash SHA-256", err);
                resolve([]);
            }
        });
    }

    async function hashWithCryptoJs(jsonSerialized) {
        const hash = CryptoJS.SHA256(jsonSerialized);
        const hashWords = hash.words;
        const hashArray = [];
        for (let i = 0; i < hashWords.length; i++) {
            hashArray.push((hashWords[i] >>> 24) & 0xff);
            hashArray.push((hashWords[i] >>> 16) & 0xff);
            hashArray.push((hashWords[i] >>> 8) & 0xff);
            hashArray.push(hashWords[i] & 0xff);
        }
        return hashArray;
    }

    function establecerWebSerialCommunication() { isWebSerial = true; isAgentePos = false; }
    function utilizarAgentePOS() { isWebSerial = false; isAgentePos = true; }
    function establecerPuertoFijo(com) { serialComFijo = com; }

    function startTimeoutForResponse(segundos) {
        stopTimeoutForResponse();
        TimeoutForResponse = setTimeout(() => { TimeOutError(); }, segundos * 1000);
    }
    function stopTimeoutForResponse() {
        if (TimeoutForResponse) { clearTimeout(TimeoutForResponse); TimeoutForResponse = null; }
    }
    function startReveivedTimeout() {
        stopReceivedTimeout();
        ReceivedTimeout = setTimeout(() => { console.warn("[Getnet POS] Esperando confirmacion inicial del POS..."); }, defaultReceivedTimeout * 1000);
    }
    function stopReceivedTimeout() {
        if (ReceivedTimeout) { clearTimeout(ReceivedTimeout); ReceivedTimeout = null; }
    }
    function TimeOutError() {
        if (typeof errorCallback === 'function') { errorCallback("Tiempo de espera agotado esperando confirmacion del POS Getnet"); }
    }
    function SetTimeErrorCallback(callback) { errorCallback = callback; }

    async function Procesar(data, segundosTimeout = defaultTimeout) {
        try {
            const jsonSerialized = await SignMessage(data);
            if (typeof LogCallback === 'function') LogCallback(jsonSerialized);
            startTimeoutForResponse(segundosTimeout);
            startReveivedTimeout();
            await SerialComunication(jsonSerialized);
        } catch (error) {
            console.error("[Getnet POS] Error enviando comando:", error);
            if (typeof errorCallback === 'function') { errorCallback("Error enviando comando al POS: " + (error.message || error)); }
        }
    }

    function MensajeRecibido(mensaje) {
        if (!mensaje) return;
        let parsedData = mensaje;
        if (mensaje.JsonSerialized && typeof mensaje.JsonSerialized === 'string') {
            try { const inner = JSON.parse(mensaje.JsonSerialized); parsedData = { ...mensaje, ...inner }; }
            catch (e) { console.warn("[Getnet POS] Error parseando JsonSerialized interno:", e); }
        }
        if (parsedData.Received === true) {
            stopReceivedTimeout();
            textoCallback = JSON.stringify(parsedData);
        } else {
            stopReceivedTimeout();
            if (parsedData.ResponseCode !== undefined || parsedData.Command === 106 || parsedData.Command === 100 || parsedData.Command === 101 || parsedData.Command === 116) {
                stopTimeoutForResponse();
            }
            textoCallback = JSON.stringify(parsedData);
            if (typeof LogCallback === 'function') LogCallback(textoCallback);
        }
        if (typeof Callback === 'function') { Callback(parsedData); }
    }

    function Poll() {
        try {
            const data = { Command: POSCommands.Function.Poll, DateTime: new Date().toISOString() };
            Procesar(data, defaultMinTimeout);
        } catch (ex) { console.error(ex); }
    }

    /**
     * Sale - Envia cobro al POS Getnet.
     *
     * Firma original (7 args) - COMPATIBLE CON LLAMADAS EXISTENTES:
     *   Getnet.Sale(amount, ticketNumber, printOnPos, saleType, sendMessage, employeeId, secondsTimeout)
     *   Ejemplo: Getnet.Sale(27990, "123456", false, 0, true, 1, 180)
     *
     * Firma extendida con cuotas (9 args):
     *   Getnet.Sale(amount, ticketNumber, printOnPos, saleType, sendMessage, employeeId, sharesNumber, sharesType, secondsTimeout)
     *   Ejemplo: Getnet.Sale(27990, "123456", false, 0, true, 1, 3, 1, 180)
     *
     * Deteccion de firma: si arg7 >= 30 Y sharesType=0 Y secondsTimeout=defaultMaxTimeout => firma original (arg7=timeout).
     */
    function Sale(
        amount,
        ticketNumber,
        printOnPos = false,
        saleType = POSCommands.SaleType.Sale,
        sendMessage = false,
        employeeId = 1,
        secondsTimeout = defaultMaxTimeout
    ) {
        try {
            if (SerialCom) SerialCom.clearBuffer();

            const timeout = parseInt(secondsTimeout, 10) || defaultMaxTimeout;

            const data = {
                Command: POSCommands.Function.Sale,
                Amount: parseInt(amount, 10),
                TicketNumber: String(ticketNumber || Date.now().toString().slice(-6)),
                PrintOnPos: Boolean(printOnPos),
                SaleType: (saleType !== undefined && saleType !== null) ? saleType : POSCommands.SaleType.Sale,
                SendMessage: Boolean(sendMessage),
                EmployeeId: parseInt(employeeId, 10) || 1,
                DateTime: new Date().toISOString(),
            };

            console.log("[Getnet POS] Enviando Venta: $" + data.Amount + " | Ticket: " + data.TicketNumber + " | Timeout: " + timeout + "s");
            Procesar(data, timeout);
        } catch (ex) {
            console.error("[Getnet Sale Error]:", ex);
        }
    }

    function LastVoucher(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.LastVoucher, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function Refund(operationId, printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.Refund, OperationId: operationId, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function Close(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.Close, DateTime: new Date().toISOString(), PrintOnPos: printOnPos }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function Totals(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.Totals, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function Details(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.Details, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function SetNormalMode(secondsTimeout) {
        if (secondsTimeout === undefined) secondsTimeout = defaultMinTimeout;
        try {
            Procesar({ Command: POSCommands.Function.SetNormalMode, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function Return(authorizationCode, amount, printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.Return, AuthorizationCode: authorizationCode, Amount: amount, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function DuplicateOthers(operationId, printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.DuplicateOthers, OperationId: operationId, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function SalesBySeller(employeeId, printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.SalesBySeller, EmployeeId: employeeId, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function TipReport(employeeId, printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultTimeout;
        try {
            Procesar({ Command: POSCommands.Function.TipReport, EmployeeId: employeeId, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function DefaultSaleType(saleType, secondsTimeout) {
        if (secondsTimeout === undefined) secondsTimeout = defaultMinTimeout;
        try {
            Procesar({ Command: POSCommands.Function.DefaultSaleType, SaleType: saleType, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function ParameterReport(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultMinTimeout;
        try {
            Procesar({ Command: POSCommands.Function.ParameterReport, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function SimReport(printOnPos, secondsTimeout) {
        if (printOnPos === undefined) printOnPos = false;
        if (secondsTimeout === undefined) secondsTimeout = defaultMinTimeout;
        try {
            Procesar({ Command: POSCommands.Function.SimReport, PrintOnPos: printOnPos, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function CancelSale(secondsTimeout) {
        if (secondsTimeout === undefined) secondsTimeout = defaultMinTimeout;
        stopTimeoutForResponse();
        stopReceivedTimeout();
        try {
            Procesar({ Command: POSCommands.Function.CancelSale, DateTime: new Date().toISOString() }, secondsTimeout);
        } catch (ex) { console.error(ex); }
    }

    function SetCallback(callback) { Callback = callback; }
    function SetLogCallback(callback) { LogCallback = callback; }

    function gSleep(ms) {
        if (ms === undefined) ms = 500;
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function connect(portObj, baudRate) {
        if (baudRate === undefined) baudRate = 115200;
        if (!SerialCom) { SerialCom = new Serial(); }
        return await SerialCom.setPort(portObj, baudRate);
    }

    async function probePortWithPoll(timeoutMs) {
        if (timeoutMs === undefined) timeoutMs = 600;
        if (!isConnected()) return false;
        return new Promise((resolve) => {
            var timer = null;
            const originalCallback = Callback;
            const probeCallback = (msg) => {
                if (msg && (msg.Command === 106 || msg.Received === true || msg.ResponseCode !== undefined)) {
                    if (timer) clearTimeout(timer);
                    Callback = originalCallback;
                    if (typeof originalCallback === 'function') originalCallback(msg);
                    resolve(true);
                }
            };
            Callback = probeCallback;
            timer = setTimeout(() => { Callback = originalCallback; resolve(false); }, timeoutMs);
            try { Poll(); } catch (e) { if (timer) clearTimeout(timer); Callback = originalCallback; resolve(false); }
        });
    }

    /**
     * autoConnect: conecta al COM previamente autorizado con reintentos progresivos.
     * Los delays [0, 400, 1000] ms permiten al OS de Windows liberar el puerto tras un refresh.
     */
    async function autoConnect(baudRate) {
        if (baudRate === undefined) baudRate = 115200;
        if (isConnected()) return SerialCom.port;
        if (typeof navigator === 'undefined' || !navigator.serial || !navigator.serial.getPorts) { return null; }
        try {
            const ports = await navigator.serial.getPorts();
            if (!ports || ports.length === 0) { return null; }
            if (!SerialCom) SerialCom = new Serial();
            const portsToTry = ports.slice().reverse(); // del mas reciente al mas antiguo
            const retryDelays = [0, 400, 1000];
            for (var pi = 0; pi < portsToTry.length; pi++) {
                var port = portsToTry[pi];
                for (var attempt = 0; attempt < retryDelays.length; attempt++) {
                    if (retryDelays[attempt] > 0) {
                        console.log("[Getnet POS] autoConnect: reintento " + attempt + " (" + retryDelays[attempt] + "ms)...");
                        await new Promise(r => setTimeout(r, retryDelays[attempt]));
                    }
                    try {
                        // Limpiar lector si el mismo puerto quedo en estado inconsistente
                        if (SerialCom.port === port && !isConnected()) {
                            SerialCom.isReading = false;
                            if (SerialCom.reader) {
                                try { await SerialCom.reader.cancel(); } catch (_) {}
                                try { SerialCom.reader.releaseLock(); } catch (_) {}
                                SerialCom.reader = null;
                            }
                        }
                        await SerialCom.setPort(port, baudRate);
                        if (isConnected()) {
                            console.log("[Getnet POS] Auto-conectado (intento " + (attempt + 1) + ").");
                            return port;
                        }
                    } catch (err) {
                        console.warn("[Getnet POS] autoConnect intento " + (attempt + 1) + " fallo:", err.message || err);
                        if (attempt < retryDelays.length - 1) {
                            try { await SerialCom.disconnect(); } catch (_) {}
                        }
                    }
                }
            }
        } catch (e) {
            console.warn("[Getnet POS] autoConnect error:", e);
        }
        return null;
    }

    function isConnected() {
        return Boolean(SerialCom && SerialCom.port && SerialCom.port.readable && SerialCom.port.writable);
    }

    async function disconnect() {
        if (SerialCom) { await SerialCom.disconnect(); SerialCom = null; }
    }

    function clearBuffer() { if (SerialCom) SerialCom.clearBuffer(); }
    function getSerialCom() { return SerialCom; }

    if (typeof window !== 'undefined') {
        window.addEventListener('pagehide', () => {
            if (SerialCom) { try { SerialCom.disconnect(); } catch (_) {} }
        });
    }

    const Getnet = {
        Poll, Sale, LastVoucher, Refund, Close, Totals, Details, SetNormalMode,
        Return, DuplicateOthers, SalesBySeller, TipReport, DefaultSaleType,
        ParameterReport, SimReport, CancelSale, POSCommands,
        SetCallback, SetTimeErrorCallback, SetLogCallback,
        establecerWebSerialCommunication, utilizarAgentePOS, establecerPuertoFijo,
        connect, autoConnect, probePortWithPoll, isConnected, disconnect, clearBuffer, getSerialCom
    };

    return { Getnet, POSCommands, default: Getnet };
});