/*!
* Librería Getnet
* Versión: 1.5.6
* Fecha: 2024-03-07
*/
let SerialCom, WebSerialCom, Callback, textoCallback, LogCallback;
var serialComFijo = "";
var TimeoutForResponse = null;
var defaultReceivedTimeout = 3;
var ReceivedTimeout = null;
var defaultTimeout = 60;
var defaultMinTimeout = 10;
var defaultMaxTimeout = 120;
var errorCallback;
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
            console.error("Error en WebSocket", error);
            reject(error);
        };
    }
    async getPorts() {
        return new Promise(async (resolve, reject) => {
            try {
                if (serialComFijo) {
                    setPort(serialComFijo);
                    resolve();
                }
                this.waitingPort = true;
                this.socket.onopen = () => {
                    this.send(JSON.stringify({ Type: "ports" }));
                    resolve();
                };
            } catch (error) {
                console.error("No se seleccionó el puerto");
                reject();
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
        this.enqueueMessage({ Type: "getnet-port", OpenParams: { Port: this.port, BaudRate: 115200 },  WriteParams: null })
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
            console.log(error)
        }
    }
    canProcess() {
        if (this.waitingPort)
            return false;
        if (new Date() - this.lastCommand >= this.espera)
            return true;
        return false;
    }
    esperarProceso() {
        return new Promise(res => setTimeout(() => {
            res();
        }, this.espera - (new Date() - this.lastCommand)))
    }
}
function openWindowPort(availablePorts) {
    document
        .querySelector("body")
        .appendChild(renderWindowPort(availablePorts.Ports));
}
function renderWindowPort(ports) {
    const dialog = document.createElement("dialog");
    dialog.open = true;
    dialog.style = `width: 100vw; height: 100vh; margin: 0px !important; back; border: 0px !important;
    position: fixed; top: 0; left: 0; background: #00000000 !important`;
    const div = document.createElement("div");
    div.style = `padding: 1rem 2rem; position: fixed !important; top: 1rem !important; left: 1rem !important; background-color: white !important;
    ; border: none !important; border-radius: 8px !important; box-shadow: 0 0 10px #00000044 !important`;
    div.innerHTML = `<p style='font-size: 16px !important; padding: 0px !important;
    line-heigth: 12px !important; font-color: black; !important'>Seleccione puerto para conectarse</p>`;
    const ul = document.createElement("ul");
    ul.style =
        "list-style: none !important; padding: 0 !important; font-size: 16px !important";
    ports.forEach((port) => {
        let li = document.createElement("li");
        li.style =
            "padding: 4px 8px !important; cursor: pointer !important; transition: background-color 150ms ease !important";
        li.addEventListener("mouseover", () => {
            li.style.backgroundColor = "#0d6efd22";
        });
        li.addEventListener("mouseout", () => {
            li.style.backgroundColor = "";
        });
        li.innerText = port;
        li.addEventListener("click", () => {
            WebSerialCom.setPort(port);
            dialog.remove();
        });
        ul.appendChild(li);
    });
    div.appendChild(ul);
    dialog.appendChild(div);
    dialog.addEventListener("click", function (e) {
        if (!div.contains(e.target)) {
            dialog.remove();
        }
    });
    return dialog;
}

class Serial {
    port = null;
    writer = null;
    reader = null;
    text = "";
    lastCommand = new Date();
    espera = 500;
    command = {
        sending: false,
        message: '',
        resend: false
    };
    async setPort() {
        return new Promise(async (resolve, reject) => {
            try {
                this.port = await navigator.serial.requestPort();
                this.openPort();
                this.startReading();
                resolve();
            } catch (error) {
                console.error("No se seleccionó el puerto");
            }
        });
    }
    openPort() {
        this.port.open({ baudRate: 115200 });
    }
    startReading() {
        if (!this.port.readable) {
            setTimeout(() => {
                this.startReading();
            }, this.espera);
            return;
        }
        this.reader = this.port.readable.getReader();
        this.readLoop();
    }
    async readLoop() {
        while (true) {
            const { value, done } = await this.reader.read();
            if (done) {
                this.reader.releaseLock();
                break;
            }
            this.text = this.text + uint8ArrayToString(value);
            try {
                const jsonData = JSON.parse(this.text);
                MensajeRecibido(jsonData);
                if (jsonData.Received == undefined)
                    SerialComunication(JSON.stringify({ Received: true }));
                this.text = "";
            } catch { }
        }
    }
    establecerWriterPuerto() {
        return new Promise(async (resolve) => {
            try {
                this.writer = await this.port.writable.getWriter();
                resolve();
            } catch {
                await this.setPort();
                resolve();
            }
        });
    }
    async handleWriterAndPort() {
        return new Promise((resolve) => {
            if (!this.writer || !this.port.writable) {
                this.command.resend = true;
                setTimeout(async () => {
                    await this.establecerWriterPuerto();
                    return this.handleWriterAndPort();
                }, this.espera);
                return;
            }
            if (this.command.resend == true) {
                this.send(this.command.message);
            }
            resolve();
        })

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
            this.send(jsonSerialized);
        } catch (error) {
            console.log('write', error)
        }
    }

    async send(jsonSerialized) {
        try {
            let encoder = new TextEncoder();
            let bytes = encoder.encode(jsonSerialized);
            const buffer = bytes.buffer;
            this.lastCommand = new Date();
            await this.writer.write(buffer);
            this.command.sending = false;
            this.command.message = '';
        } catch (error) {
            console.error(error);
        }
    }
    canProcess() {
        if (new Date() - this.lastCommand >= this.espera)
            return true;
        return false;
    }
    esperarProceso() {
        return new Promise(res => setTimeout(() => {
            res();
        }, this.espera - (new Date() - this.lastCommand)))
    }
}

function uint8ArrayToString(uint8Array) {
    let decoder = new TextDecoder();
    return decoder.decode(uint8Array);
}

async function connectWebSerial() {
    return new Promise(async (resolve, reject) => {
        WebSerialCom.setPort("")
        resolve();
    })
}

async function WebSerialComunication(jsonSerialized) {
    if (!WebSerialCom && !isAgentePos) {
        WebSerialCom = new WebSerial();
    }
    await connectWebSerial();
    WebSerialCom.write(jsonSerialized);
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
    return navigator.userAgent.includes("Firefox") || isWebSerial;
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
    return new Promise(async (resolve, reject) => {
        try {
            if (CryptoJS)
                resolve(hashWithCryptoJs(jsonSerialized))
        }catch {
            const encoder = new TextEncoder();
            const data = encoder.encode(jsonSerialized);
            const hash = await window.crypto.subtle.digest("SHA-256", data);
            const hashArray = Array.from(new Uint8Array(hash));
            resolve(hashArray);
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
        return;
    } catch (error) {
        throw new Error("Se debe seleccionar webserial para utilizar esta función")
    }
}
function establecerPuertoFijo(puerto) {
    if (getIsWebSerialCommunication()) {
        serialComFijo = puerto;
        return;
    }
    throw new Error("Se debe seleccionar webserial para utilizar esta función")
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
    }
}
function TimeOutError() {
    if (!errorCallback) {
        errorCallback = () => {
            console.log("error");
        };
    }
    errorCallback();
}
function SetTimeErrorCallback(callback) {
    errorCallback = callback;
}
async function Procesar(data, segundosTimeout = defaultTimeout) {
    try {
        const jsonSerialized = await SignMessage(data);
        LogCallback(jsonSerialized);
        startTimeoutForResponse(segundosTimeout);
        startReveivedTimeout();
        SerialComunication(jsonSerialized);
    } catch (error) {
        console.error(error);
    }
}
function MensajeRecibido(mensaje) {
    if (mensaje.Received) {
        stopReceivedTimeout();
        textoCallback = JSON.stringify(mensaje);
    } else {
        stopTimeoutForResponse();
        textoCallback += JSON.stringify(mensaje);
        LogCallback(textoCallback);
    }
    Callback(mensaje);
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
    saleType,
    sendMessage = false,
    employeeId = 1,
    secondsTimeout = defaultMaxTimeout
) {
    try {
        const data = {
            Command: POSCommands.Function.Sale,
            Amount: amount,
            TicketNumber: ticketNumber,
            PrintOnPos: printOnPos,
            SaleType: saleType,
            SendMessage: sendMessage,
            EmployeeId: employeeId,
            DateTime: new Date().toISOString(),
        };
        Procesar(data, secondsTimeout);
    } catch (ex) {
        console.error(ex);
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

export default {
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
    establecerPuertoFijo
};
