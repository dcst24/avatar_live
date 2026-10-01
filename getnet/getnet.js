/*!
* Librería Getnet
* Versión: 1.5.6 (Adaptado para integración directa Web Serial / USB POS)
* Fecha: 2024-03-07 / 2026-10-01
*/
let SerialCom = null;
let WebSerialCom = null;
let Callback = (msg) => { console.log("[Getnet Callback]", msg); };
let textoCallback = "";
let LogCallback = (log) => { console.log("[Getnet Log]", log); };
var serialComFijo = "";
var TimeoutForResponse = null;
var defaultReceivedTimeout = 5;
var ReceivedTimeout = null;
var defaultTimeout = 60;
var defaultMinTimeout = 10;
var defaultMaxTimeout = 120;
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
        this.espera = 300;
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
        const buffer = bytes.buffer;
        return buffer;
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
            await gSleep(300);
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
        return new Promise(res => setTimeout(() => {
            res();
        }, this.espera - (new Date() - this.lastCommand)));
    }
}

class Serial {
    port = null;
    writer = null;
    reader = null;
    text = "";
    lastCommand = new Date();
    espera = 300;
    baudRate = 115200;
    isReading = false;
    command = {
        sending: false,
        message: '',
        resend: false
    };

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
                await this.port.open({ baudRate: this.baudRate });
                console.log(`[Getnet POS] Puerto abierto exitosamente a ${this.baudRate} baud`);
            } catch (err) {
                // Si el puerto ya estaba abierto, continuar
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
        this.reader = this.port.readable.getReader();
        this.readLoop();
    }

    async readLoop() {
        try {
            while (true) {
                const { value, done } = await this.reader.read();
                if (done) {
                    if (this.reader) this.reader.releaseLock();
                    this.isReading = false;
                    break;
                }
                const chunk = uint8ArrayToString(value);
                this.text += chunk;

                // Intentar parsear JSON completo
                try {
                    const jsonData = JSON.parse(this.text);
                    MensajeRecibido(jsonData);
                    if (jsonData.Received === undefined) {
                        SerialComunication(JSON.stringify({ Received: true }));
                    }
                    this.text = "";
                } catch (jsonErr) {
                    // Buffer parcial, esperar siguiente chunk
                }
            }
        } catch (err) {
            console.warn("[Getnet POS] Error en bucle de lectura:", err);
            this.isReading = false;
        }
    }

    async establecerWriterPuerto() {
        try {
            if (this.port && this.port.writable) {
                this.writer = await this.port.writable.getWriter();
            }
        } catch (e) {
            console.warn("[Getnet POS] Error al obtener writer:", e);
        }
    }

    async handleWriterAndPort() {
        if (!this.writer || !this.port || !this.port.writable) {
            this.command.resend = true;
            await this.establecerWriterPuerto();
        }
        if (this.command.resend === true && this.command.message) {
            await this.send(this.command.message);
        }
    }

    async write(jsonSerialized) {
        try {
            this.command.resend = false;
            this.command.sending = true;
            this.command.message = jsonSerialized;
            await this.handleWriterAndPort();
            while (!this.canProcess()) {
                await this.esperarProceso();
            }
            await this.send(jsonSerialized);
        } catch (error) {
            console.error('[Getnet POS] Error en write:', error);
        }
    }

    async send(jsonSerialized) {
        try {
            if (!this.writer) {
                await this.establecerWriterPuerto();
            }
            if (!this.writer) throw new Error("No hay canal de escritura disponible hacia el POS");

            let encoder = new TextEncoder();
            let bytes = encoder.encode(jsonSerialized);
            this.lastCommand = new Date();
            await this.writer.write(bytes);
            this.command.sending = false;
            this.command.message = '';
            // Liberar writer después de enviar para no bloquear
            this.writer.releaseLock();
            this.writer = null;
        } catch (error) {
            console.error('[Getnet POS] Error en send:', error);
            if (this.writer) {
                try { this.writer.releaseLock(); } catch (_) {}
                this.writer = null;
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
                this.reader.releaseLock();
                this.reader = null;
            }
            if (this.writer) {
                try { this.writer.releaseLock(); } catch (_) {}
                this.writer = null;
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
        TimeOutError();
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
        errorCallback("Timeout esperando respuesta del terminal POS Getnet");
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
    if (mensaje && mensaje.Received) {
        stopReceivedTimeout();
        textoCallback = JSON.stringify(mensaje);
    } else {
        stopTimeoutForResponse();
        textoCallback += JSON.stringify(mensaje);
        if (typeof LogCallback === 'function') LogCallback(textoCallback);
    }
    if (typeof Callback === 'function') {
        Callback(mensaje);
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

if (typeof window !== 'undefined') {
    window.Getnet = Getnet;
    window.POSCommands = POSCommands;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { POSCommands, Getnet, default: Getnet };
}

