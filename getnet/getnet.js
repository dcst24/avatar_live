/*!
* Librería Getnet
* Versión: 1.5.7 (Adaptado para integración directa Web Serial / USB POS)
* Fecha: 2024-03-07 / 2026-10-01
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
    var defaultReceivedTimeout = 30;
    var ReceivedTimeout = null;
    var defaultTimeout = 120;
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
                    console.error("No se seleccionó el puerto", error);
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
        encodeMensaje(mensaje) {
            let encoder = new TextEncoder();
            let bytes = encoder.encode(mensaje);
            return bytes.buffer;
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
                if (this.queue.length === 0) {
                    return;
                }
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
                while (!this.canProcess()) {
                    await this.esperarProceso();
                }
                this.lastCommand = new Date();
                this.socket.send(JSON.stringify(mensaje));
                resolve();
            });
        }
        send(mensaje) {
            try {
                this.socket.send(mensaje);
            } catch (error) {
                console.log(error);
            }
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
        lastCommand = new Date();
        espera = 250;
        baudRate = 115200;
        isReading = false;

        async setPort(portInstance = null, baudRate = 115200) {
            this.baudRate = baudRate || 115200;
            try {
                if (portInstance) {
                    this.port = portInstance;
                } else if (navigator && navigator.serial) {
                    this.port = await navigator.serial.requestPort();
                } else {
                    throw new Error("Web Serial API no soportada en este navegador. Use Chrome, Edge u Opera.");
                }
                await this.openPort();
                this.startReading();
                return this.port;
            } catch (error) {
                console.error("Error al seleccionar o configurar el puerto COM:", error);
                throw error;
            }
        }

        async openPort() {
            if (this.port) {
                try {
                    if (!this.port.readable || !this.port.writable) {
                        await this.port.open({ baudRate: this.baudRate });
                        console.log(`[Getnet POS] Puerto abierto exitosamente a ${this.baudRate} baud`);
                    }
                } catch (err) {
                    console.warn("[Getnet POS] Aviso al abrir puerto:", err);
                }
            }
        }

        startReading() {
            if (!this.port || !this.port.readable) {
                setTimeout(() => {
                    this.startReading();
                }, this.espera);
                return;
            }
            if (this.isReading) return;
            this.isReading = true;
            this.readLoop();
        }

        async readLoop() {
            try {
                while (this.port && this.port.readable && this.isReading) {
                    this.reader = this.port.readable.getReader();
                    try {
                        while (true) {
                            const { value, done } = await this.reader.read();
                            if (done) break;
                            const chunk = uint8ArrayToString(value);
                            this.text += chunk;

                            // Procesamiento robusto de mensajes JSON del POS
                            this.processBuffer();
                        }
                    } catch (readErr) {
                        console.warn("[Getnet POS] Error en bloque lector:", readErr);
                        break;
                    } finally {
                        if (this.reader) {
                            try { this.reader.releaseLock(); } catch (_) {}
                            this.reader = null;
                        }
                    }
                }
            } catch (err) {
                console.warn("[Getnet POS] Error en bucle de lectura:", err);
            } finally {
                this.isReading = false;
            }
        }

        processBuffer() {
            let buffer = this.text.trim();
            if (!buffer) return;

            // 1. Intentar parsear si todo el buffer es un objeto JSON
            if (buffer.startsWith('{') && buffer.endsWith('}')) {
                try {
                    const jsonData = JSON.parse(buffer);
                    this.text = "";
                    MensajeRecibido(jsonData);
                    if (jsonData.Received === undefined) {
                        this.sendAck();
                    }
                    return;
                } catch (_) {}
            }

            // 2. Extraer objetos JSON balanceados { ... } del buffer
            let startIndex = buffer.indexOf('{');
            while (startIndex !== -1) {
                let depth = 0;
                let endIndex = -1;
                for (let i = startIndex; i < buffer.length; i++) {
                    if (buffer[i] === '{') depth++;
                    else if (buffer[i] === '}') {
                        depth--;
                        if (depth === 0) {
                            endIndex = i;
                            break;
                        }
                    }
                }

                if (endIndex !== -1) {
                    const jsonCandidate = buffer.slice(startIndex, endIndex + 1);
                    try {
                        const jsonData = JSON.parse(jsonCandidate);
                        buffer = buffer.slice(endIndex + 1).trim();
                        this.text = buffer;
                        MensajeRecibido(jsonData);
                        if (jsonData.Received === undefined) {
                            this.sendAck();
                        }
                        startIndex = buffer.indexOf('{');
                    } catch (e) {
                        break;
                    }
                } else {
                    break;
                }
            }
        }

        async sendAck() {
            try {
                // Confirmación silenciosa de recepción hacia el POS
                const ackMsg = JSON.stringify({ Received: true });
                await this.send(ackMsg);
            } catch (_) {}
        }

        async write(jsonSerialized) {
            try {
                while (!this.canProcess()) {
                    await this.esperarProceso();
                }
                await this.send(jsonSerialized);
            } catch (error) {
                console.error('[Getnet POS] Error en write:', error);
            }
        }

        async send(dataString) {
            if (!this.port || !this.port.writable) {
                throw new Error("No hay canal de escritura disponible hacia el POS");
            }
            let writer = null;
            try {
                writer = this.port.writable.getWriter();
                let encoder = new TextEncoder();
                let bytes = encoder.encode(dataString);
                this.lastCommand = new Date();
                await writer.write(bytes);
            } catch (error) {
                console.error('[Getnet POS] Error en send:', error);
                throw error;
            } finally {
                if (writer) {
                    try { writer.releaseLock(); } catch (_) {}
                }
            }
        }

        canProcess() {
            if (new Date() - this.lastCommand >= this.espera) return true;
            return false;
        }

        esperarProceso() {
            return new Promise(res => setTimeout(res, Math.max(10, this.espera - (new Date() - this.lastCommand))));
        }

        async disconnect() {
            try {
                this.isReading = false;
                if (this.reader) {
                    await this.reader.cancel();
                    try { this.reader.releaseLock(); } catch (_) {}
                    this.reader = null;
                }
                if (this.port) {
                    await this.port.close();
                    this.port = null;
                }
                console.log("[Getnet POS] Puerto desconectado");
            } catch (e) {
                console.warn("[Getnet POS] Error cerrando puerto:", e);
            }
        }
    }

    function uint8ArrayToString(uint8Array) {
        let decoder = new TextDecoder();
        return decoder.decode(uint8Array);
    }

    async function connectWebSerial() {
        return new Promise((resolve) => {
            if (WebSerialCom) WebSerialCom.setPort("");
            resolve();
        });
    }

    async function WebSerialComunication(jsonSerialized) {
        if (!WebSerialCom && !isAgentePos) {
            WebSerialCom = new WebSerial();
        }
        await connectWebSerial();
        if (WebSerialCom) WebSerialCom.write(jsonSerialized);
    }

    async function SerialComunication(jsonSerialized) {
        if (getIsWebSerialCommunication()) {
            WebSerialComunication(jsonSerialized);
            return;
        }
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
                var signedData = {
                    JsonSerialized: jsonSerialized,
                    Sign: sign.toUpperCase(),
                };
                resolve(JSON.stringify(signedData));
            } catch (error) {
                reject(error);
            }
        });
    }

    function SignWithSha256(jsonSerialized) {
        return new Promise(async (resolve, reject) => {
            try {
                const hashArray = await hashJsonSerialized(jsonSerialized);
                const hashHex = hashArray
                    .map((b) => b.toString(16).padStart(2, "0"))
                    .join("");
                resolve(hashHex);
            } catch (error) {
                reject(error);
            }
        });
    }

    async function hashJsonSerialized(jsonSerialized) {
        return new Promise(async (resolve) => {
            try {
                if (typeof CryptoJS !== 'undefined' && CryptoJS.SHA256) {
                    resolve(hashWithCryptoJs(jsonSerialized));
                    return;
                }
            } catch (_) {}

            try {
                const encoder = new TextEncoder();
                const data = encoder.encode(jsonSerialized);
                const hash = await window.crypto.subtle.digest("SHA-256", data);
                const hashArray = Array.from(new Uint8Array(hash));
                resolve(hashArray);
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

    function establecerWebSerialCommunication() {
        isWebSerial = true;
    }

    function utilizarAgentePOS() {
        try {
            isWebSerial = true;
            isAgentePos = true;
            if (!WebSerialCom) {
                WebSerialCom = new WebSerial();
            }
            WebSerialCom.useGetnetPosAgent();
        } catch (error) {
            throw new Error("Se debe seleccionar webserial para utilizar esta función");
        }
    }

    function establecerPuertoFijo(puerto) {
        if (getIsWebSerialCommunication()) {
            serialComFijo = puerto;
            return;
        }
        throw new Error("Se debe seleccionar webserial para utilizar esta función");
    }

    function startTimeoutForResponse(segundos) {
        stopTimeoutForResponse();
        TimeoutForResponse = setTimeout(() => {
            TimeOutError();
        }, segundos * 1000);
    }

    function stopTimeoutForResponse() {
        if (TimeoutForResponse) {
            clearTimeout(TimeoutForResponse);
            TimeoutForResponse = null;
        }
    }

    function startReveivedTimeout() {
        stopReceivedTimeout();
        ReceivedTimeout = setTimeout(() => {
            // No enviar timeout general si ya se envió el comando
            console.warn("[Getnet POS] Esperando ACK inicial del POS...");
        }, defaultReceivedTimeout * 1000);
    }

    function stopReceivedTimeout() {
        if (ReceivedTimeout) {
            clearTimeout(ReceivedTimeout);
            ReceivedTimeout = null;
        }
    }

    function TimeOutError() {
        if (typeof errorCallback === 'function') {
            errorCallback("Tiempo de espera agotado esperando confirmación del POS Getnet");
        }
    }

    function SetTimeErrorCallback(callback) {
        errorCallback = callback;
    }

    async function Procesar(data, segundosTimeout = defaultTimeout) {
        try {
            const jsonSerialized = await SignMessage(data);
            if (typeof LogCallback === 'function') LogCallback(jsonSerialized);
            startTimeoutForResponse(segundosTimeout);
            startReveivedTimeout();
            await SerialComunication(jsonSerialized);
        } catch (error) {
            console.error("[Getnet POS] Error procesando mensaje:", error);
        }
    }

    function MensajeRecibido(mensaje) {
        if (!mensaje) return;

        // Desempaquetar JsonSerialized si el POS responde con formato firmado
        let parsedData = mensaje;
        if (mensaje.JsonSerialized && typeof mensaje.JsonSerialized === 'string') {
            try {
                const inner = JSON.parse(mensaje.JsonSerialized);
                parsedData = { ...mensaje, ...inner };
            } catch (e) {
                console.warn("[Getnet POS] Error parseando JsonSerialized interno:", e);
            }
        }

        if (parsedData.Received) {
            stopReceivedTimeout();
            textoCallback = JSON.stringify(parsedData);
        } else {
            // Si el mensaje es una respuesta intermedia o final de transacción
            stopReceivedTimeout();
            if (parsedData.ResponseCode !== undefined || parsedData.Command === 106 || parsedData.Command === 100 || parsedData.Command === 101) {
                stopTimeoutForResponse();
            }
            textoCallback = JSON.stringify(parsedData);
            if (typeof LogCallback === 'function') LogCallback(textoCallback);
        }

        if (typeof Callback === 'function') {
            Callback(parsedData);
        }
    }

    function Poll() {
        try {
            const data = {
                Command: POSCommands.Function.Poll,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, defaultMinTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Sale(
        amount,
        ticketNumber,
        printOnPos = false,
        saleType = POSCommands.SaleType.Sale,
        sendMessage = true,
        employeeId = 1,
        secondsTimeout = defaultMaxTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.Sale,
                Amount: parseInt(amount, 10),
                TicketNumber: String(ticketNumber || Date.now().toString().slice(-6)),
                PrintOnPos: Boolean(printOnPos),
                SaleType: saleType !== undefined ? saleType : POSCommands.SaleType.Sale,
                SendMessage: Boolean(sendMessage),
                EmployeeId: parseInt(employeeId, 10) || 1,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error("[Getnet Sale Error]:", ex);
        }
    }

    function LastVoucher(printOnPos = false, secondsTimeout = defaultTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.LastVoucher,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Refund(
        operationId,
        printOnPos = false,
        secondsTimeout = defaultTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.Refund,
                OperationId: operationId,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Close(printOnPos = false, secondsTimeout = defaultTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.Close,
                DateTime: new Date().toISOString(),
                PrintOnPos: printOnPos,
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Totals(printOnPos = false, secondsTimeout = defaultTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.Totals,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Details(printOnPos = false, secondsTimeout = defaultTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.Details,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function SetNormalMode(secondsTimeout = defaultMinTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.SetNormalMode,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function Return(
        authorizationCode,
        amount,
        printOnPos = false,
        secondsTimeout = defaultTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.Return,
                AuthorizationCode: authorizationCode,
                Amount: amount,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function DuplicateOthers(
        operationId,
        printOnPos = false,
        secondsTimeout = defaultTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.DuplicateOthers,
                OperationId: operationId,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function SalesBySeller(
        employeeId,
        printOnPos = false,
        secondsTimeout = defaultTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.SalesBySeller,
                EmployeeId: employeeId,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function TipReport(
        employeeId,
        printOnPos = false,
        secondsTimeout = defaultTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.TipReport,
                EmployeeId: employeeId,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function DefaultSaleType(saleType, secondsTimeout = defaultMinTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.DefaultSaleType,
                SaleType: saleType,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function ParameterReport(
        printOnPos = false,
        secondsTimeout = defaultMinTimeout
    ) {
        try {
            const data = {
                Command: POSCommands.Function.ParameterReport,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function SimReport(printOnPos = false, secondsTimeout = defaultMinTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.SimReport,
                PrintOnPos: printOnPos,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function CancelSale(secondsTimeout = defaultMinTimeout) {
        try {
            const data = {
                Command: POSCommands.Function.CancelSale,
                DateTime: new Date().toISOString(),
            };
            Procesar(data, secondsTimeout);
        } catch (ex) {
            console.error(ex);
        }
    }

    function SetCallback(callback) {
        Callback = callback;
    }

    function SetLogCallback(callback) {
        LogCallback = callback;
    }

    function gSleep(ms = 500) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function connect(portObj = null, baudRate = 115200) {
        if (!SerialCom) {
            SerialCom = new Serial();
        }
        return await SerialCom.setPort(portObj, baudRate);
    }

    async function autoConnect(baudRate = 115200) {
        if (typeof navigator !== 'undefined' && navigator.serial && navigator.serial.getPorts) {
            try {
                const ports = await navigator.serial.getPorts();
                if (ports && ports.length > 0) {
                    if (!SerialCom) SerialCom = new Serial();
                    await SerialCom.setPort(ports[0], baudRate);
                    return ports[0];
                }
            } catch (e) {
                console.warn("[Getnet POS] autoConnect aviso:", e);
            }
        }
        return null;
    }

    function isConnected() {
        return Boolean(SerialCom && SerialCom.port);
    }

    async function disconnect() {
        if (SerialCom) {
            await SerialCom.disconnect();
            SerialCom = null;
        }
    }

    function getSerialCom() {
        return SerialCom;
    }

    const Getnet = {
        Poll,
        Sale,
        LastVoucher,
        Refund,
        Close,
        Totals,
        Details,
        SetNormalMode,
        Return,
        DuplicateOthers,
        SalesBySeller,
        TipReport,
        DefaultSaleType,
        ParameterReport,
        SimReport,
        CancelSale,
        POSCommands,
        SetCallback,
        SetTimeErrorCallback,
        SetLogCallback,
        establecerWebSerialCommunication,
        utilizarAgentePOS,
        establecerPuertoFijo,
        connect,
        autoConnect,
        isConnected,
        disconnect,
        getSerialCom
    };

    return { Getnet, POSCommands, default: Getnet };
});
