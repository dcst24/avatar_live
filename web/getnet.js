/*!
* Librería Getnet
* Versión: 1.5.8 (Integración Web Serial Directa / USB POS Terminal)
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
                if (!targetPort) {
                    throw new Error("No se seleccionó ningún puerto COM.");
                }

                if (this.port && this.port !== targetPort) {
                    await this.disconnect();
                }

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

        clearBuffer() {
            this.text = "";
        }

        async openPort() {
            if (this.port) {
                if (!this.port.readable || !this.port.writable) {
                    try {
                        await this.port.open({ baudRate: this.baudRate });
                        console.log(`[Getnet POS] Puerto COM abierto exitosamente a ${this.baudRate} baud`);
                    } catch (err) {
                        if (err.message && err.message.includes('already open')) {
                            // Ya estaba abierto, continuar normalmente
                            return;
                        }
                        // Si falló por lock transitorio en Windows, intentar liberar reader y reintentar
                        console.warn("[Getnet POS] Aviso al abrir puerto, reintentando tras limpieza...", err);
                        if (this.reader) {
                            try { await this.reader.cancel(); } catch(_) {}
                            try { this.reader.releaseLock(); } catch(_) {}
                            this.reader = null;
                        }
                        await new Promise(r => setTimeout(r, 150));
                        await this.port.open({ baudRate: this.baudRate });
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
            while (this.isReading && this.port && this.port.readable) {
                try {
                    this.reader = this.port.readable.getReader();
                    while (true) {
                        const { value, done } = await this.reader.read();
                        if (done) break;
                        if (value) {
                            if (this.openedAt && (Date.now() - this.openedAt < 400)) {
                                // Descartar bytes residuales que estaban en el chip UART antes de conectar
                                this.text = "";
                                continue;
                            }
                            this.text += textDecoder.decode(value, { stream: true });
                            this.processBuffer();
                        }
                    }
                } catch (readErr) {
                    console.warn("[Getnet POS] Lectura serial finalizada:", readErr);
                    break;
                } finally {
                    if (this.reader) {
                        try { this.reader.releaseLock(); } catch (_) {}
                        this.reader = null;
                    }
                }
                if (!this.isReading || !this.port || !this.port.readable) break;
                await new Promise(r => setTimeout(r, 200));
            }
            this.isReading = false;
        }

        processBuffer() {
            let str = this.text;
            if (!str || str.indexOf('{') === -1) return;

            while (true) {
                const start = str.indexOf('{');
                if (start === -1) {
                    str = "";
                    break;
                }

                let depth = 0;
                let end = -1;
                for (let i = start; i < str.length; i++) {
                    if (bufferCharCheck(str, i, '{')) depth++;
                    else if (bufferCharCheck(str, i, '}')) {
                        depth--;
                        if (depth === 0) {
                            end = i;
                            break;
                        }
                    }
                }

                if (end === -1) {
                    // Mensaje JSON incompleto: mantener buffer desde start para el siguiente bloque
                    if (start > 0) {
                        str = str.slice(start);
                    }
                    break;
                }

                const jsonCandidate = str.slice(start, end + 1);
                str = str.slice(end + 1);

                try {
                    const parsed = JSON.parse(jsonCandidate);
                    MensajeRecibido(parsed);
                } catch (e) {
                    console.warn("[Getnet POS] JSON malformado recibido:", e);
                }
            }
            this.text = str;
        }

        async write(jsonSerialized) {
            try {
                while (!this.canProcess()) {
                    await this.esperarProceso();
                }
                await this.send(jsonSerialized);
            } catch (error) {
                console.error('[Getnet POS] Error en write:', error);
                throw error;
            }
        }

        async send(dataString) {
            if (!this.port || !this.port.writable) {
                throw new Error("El puerto POS Getnet no está abierto para escritura");
            }
            let writer = null;
            try {
                writer = this.port.writable.getWriter();
                const encoder = new TextEncoder();
                const bytes = encoder.encode(dataString);
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
            return (new Date() - this.lastCommand) >= this.espera;
        }

        esperarProceso() {
            const remaining = Math.max(10, this.espera - (new Date() - this.lastCommand));
            return new Promise(res => setTimeout(res, remaining));
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

    function bufferCharCheck(str, index, char) {
        return str[index] === char;
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
            await WebSerialComunication(jsonSerialized);
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
            console.warn("[Getnet POS] Esperando confirmación inicial del POS...");
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
            console.error("[Getnet POS] Error enviando comando:", error);
            if (typeof errorCallback === 'function') {
                errorCallback("Error enviando comando al POS: " + (error.message || error));
            }
        }
    }

    function MensajeRecibido(mensaje) {
        if (!mensaje) return;

        // Desempaquetar JsonSerialized si el POS responde en formato firmado
        let parsedData = mensaje;
        if (mensaje.JsonSerialized && typeof mensaje.JsonSerialized === 'string') {
            try {
                const inner = JSON.parse(mensaje.JsonSerialized);
                parsedData = { ...mensaje, ...inner };
            } catch (e) {
                console.warn("[Getnet POS] Error parseando JsonSerialized interno:", e);
            }
        }

        if (parsedData.Received === true) {
            stopReceivedTimeout();
            textoCallback = JSON.stringify(parsedData);
        } else {
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
        sharesNumber = 1,
        sharesType = 0,
        secondsTimeout = defaultMaxTimeout
    ) {
        try {
            if (SerialCom) SerialCom.clearBuffer();

            // Soportar pase por objeto: Getnet.Sale({ amount, cuotas, ... })
            let finalAmount = amount;
            let finalTicket = ticketNumber;
            let finalPrint = printOnPos;
            let finalSaleType = saleType;
            let finalSendMessage = sendMessage;
            let finalEmployeeId = employeeId;
            let finalCuotas = sharesNumber;
            let finalSharesType = sharesType;
            let finalTimeout = secondsTimeout;

            if (typeof amount === 'object' && amount !== null) {
                finalAmount = amount.amount || amount.Amount || 0;
                finalTicket = amount.ticketNumber || amount.TicketNumber || Date.now().toString().slice(-6);
                finalPrint = Boolean(amount.printOnPos || amount.PrintOnPos || false);
                finalSaleType = amount.saleType !== undefined ? amount.saleType : (amount.SaleType !== undefined ? amount.SaleType : POSCommands.SaleType.Sale);
                finalSendMessage = amount.sendMessage !== undefined ? Boolean(amount.sendMessage) : true;
                finalEmployeeId = amount.employeeId || amount.EmployeeId || 1;
                finalCuotas = amount.sharesNumber || amount.SharesNumber || amount.cuotas || amount.Cuotas || amount.installments || amount.Installments || 1;
                finalSharesType = amount.sharesType !== undefined ? amount.sharesType : (amount.SharesType !== undefined ? amount.SharesType : 0);
                finalTimeout = amount.timeout || amount.secondsTimeout || defaultMaxTimeout;
            } else if (typeof sharesNumber === 'number' && sharesNumber > 50 && sharesType === 0 && secondsTimeout === defaultMaxTimeout) {
                // Caso legado donde el 7mo argumento era timeout (ej. Getnet.Sale(amount, ticket, false, 0, true, 1, 180))
                finalTimeout = sharesNumber;
                finalCuotas = 1;
                finalSharesType = 0;
            }

            const numCuotas = parseInt(finalCuotas, 10) || 1;
            const isCuotas = numCuotas > 1;
            // Para Venta en Cuotas: Tipo 1 = Cuotas Comercio (Sin Interés), Tipo 2 = Cuotas Banco, Tipo 3 = Cuotas Normales
            // Para Venta Directa / Contado (1 cuota): Tipo 0 = Sin cuotas (Venta Directa)
            const resolvedSharesType = isCuotas ? (parseInt(finalSharesType, 10) || 1) : 0;
            const resolvedSharesNumber = isCuotas ? numCuotas : 0;

            const data = {
                Command: POSCommands.Function.Sale,
                Amount: parseInt(finalAmount, 10),
                TicketNumber: String(finalTicket || Date.now().toString().slice(-6)),
                PrintOnPos: Boolean(finalPrint),
                SaleType: finalSaleType !== undefined ? finalSaleType : POSCommands.SaleType.Sale,
                SendMessage: Boolean(finalSendMessage),
                EmployeeId: parseInt(finalEmployeeId, 10) || 1,
                // Mapeo exhaustivo para todas las revisiones de firmware POS Getnet / Santander Chile:
                SharesNumber: resolvedSharesNumber,
                SharesType: resolvedSharesType,
                Shares: resolvedSharesNumber,
                ShareNumber: resolvedSharesNumber,
                ShareType: resolvedSharesType,
                Installments: isCuotas ? numCuotas : 1,
                InstallmentsNumber: resolvedSharesNumber,
                InstallmentType: resolvedSharesType,
                Cuotas: numCuotas,
                NumeroCuotas: resolvedSharesNumber,
                TipoCuota: resolvedSharesType,
                TipoCuotas: resolvedSharesType,
                Quotas: numCuotas,
                QuotaNumber: resolvedSharesNumber,
                QuotaType: resolvedSharesType,
                SharesQuantity: resolvedSharesNumber,
                SharesCount: resolvedSharesNumber,
                DateTime: new Date().toISOString(),
            };

            console.log(`[Getnet POS] Enviando Venta: $${data.Amount} | Cuotas: ${numCuotas} (SharesNumber: ${resolvedSharesNumber}, SharesType: ${resolvedSharesType}) | Ticket: ${data.TicketNumber}`);
            Procesar(data, finalTimeout);
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

    function SetTimeErrorCallback(callback) {
        errorCallback = callback;
    }

    function establecerWebSerialCommunication() {
        isWebSerial = true;
        isAgentePos = false;
    }

    function utilizarAgentePOS() {
        isWebSerial = false;
        isAgentePos = true;
    }

    function establecerPuertoFijo(com) {
        serialComFijo = com;
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

    async function probePortWithPoll(timeoutMs = 600) {
        if (!isConnected()) return false;
        return new Promise((resolve) => {
            let timer = null;
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
            timer = setTimeout(() => {
                Callback = originalCallback;
                resolve(false);
            }, timeoutMs);
            try {
                Poll();
            } catch (e) {
                if (timer) clearTimeout(timer);
                Callback = originalCallback;
                resolve(false);
            }
        });
    }

    async function autoConnect(baudRate = 115200) {
        if (isConnected()) return SerialCom.port;
        if (typeof navigator !== 'undefined' && navigator.serial && navigator.serial.getPorts) {
            try {
                const ports = await navigator.serial.getPorts();
                if (ports && ports.length > 0) {
                    if (!SerialCom) SerialCom = new Serial();

                    // Si solo hay 1 puerto previamente autorizado por el usuario:
                    if (ports.length === 1) {
                        try {
                            await SerialCom.setPort(ports[0], baudRate);
                            if (isConnected()) {
                                console.log("[Getnet POS] Auto-conectado con éxito al único puerto autorizado.");
                                return ports[0];
                            }
                        } catch (err1) {
                            console.warn("[Getnet POS] Reintentando conexión de puerto tras breve espera...", err1);
                            try { await SerialCom.disconnect(); } catch (_) {}
                            await new Promise(r => setTimeout(r, 200));
                            try {
                                await SerialCom.setPort(ports[0], baudRate);
                                if (isConnected()) return ports[0];
                            } catch (err2) {
                                console.warn("[Getnet POS] Segundo intento falló:", err2);
                            }
                        }
                    } else {
                        // Múltiples puertos autorizados: sondear del más reciente al más antiguo con Poll
                        for (let i = ports.length - 1; i >= 0; i--) {
                            const port = ports[i];
                            try {
                                await SerialCom.setPort(port, baudRate);
                                if (isConnected()) {
                                    const responded = await probePortWithPoll(450);
                                    if (responded) {
                                        console.log(`[Getnet POS] POS Getnet verificado y respondiendo en puerto [${i}].`);
                                        return port;
                                    } else {
                                        console.log(`[Getnet POS] Puerto [${i}] abierto pero POS no respondió Poll. Probando siguiente...`);
                                        await SerialCom.disconnect();
                                    }
                                }
                            } catch (e) {
                                console.warn(`[Getnet POS] Error probando puerto [${i}]:`, e);
                                try { await SerialCom.disconnect(); } catch (_) {}
                            }
                        }
                        // Si ninguno respondió con Poll pero hay puertos, conectar al último
                        if (ports.length > 0) {
                            try {
                                await SerialCom.setPort(ports[ports.length - 1], baudRate);
                                if (isConnected()) return ports[ports.length - 1];
                            } catch (_) {}
                        }
                    }
                }
            } catch (e) {
                console.warn("[Getnet POS] autoConnect error general:", e);
            }
        }
        return null;
    }

    function isConnected() {
        return Boolean(SerialCom && SerialCom.port && SerialCom.port.readable && SerialCom.port.writable);
    }

    async function disconnect() {
        if (SerialCom) {
            await SerialCom.disconnect();
            SerialCom = null;
        }
    }

    function clearBuffer() {
        if (SerialCom) SerialCom.clearBuffer();
    }

    function getSerialCom() {
        return SerialCom;
    }

    if (typeof window !== 'undefined') {
        window.addEventListener('beforeunload', () => {
            if (SerialCom) {
                try { SerialCom.disconnect(); } catch (_) {}
            }
        });
        window.addEventListener('pagehide', () => {
            if (SerialCom) {
                try { SerialCom.disconnect(); } catch (_) {}
            }
        });
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
        probePortWithPoll,
        isConnected,
        disconnect,
        clearBuffer,
        getSerialCom
    };

    return { Getnet, POSCommands, default: Getnet };
});
