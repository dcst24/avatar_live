const POSCommands = require('./PosCommands');
const { SerialAgent } = require('./SerialAgent');
const PosConfig = require("./PosConfig");
const { IpAgent } = require('./IpAgent');
const Utils = require('./Utils');
const exceptions = require('./exceptions/exceptions');
const Requests = require('./requests');

let instancia;
function getInstance (callback, timeOutResponseError, timeOutReceivedError) {
    if (!instancia)
        instancia = new POSIntegrado(callback, timeOutResponseError, timeOutReceivedError);
    return instancia;
}
class POSIntegrado {
    serialCom = null;
    IpCom = null;
    TimeoutForResponse = null;
    ReceivedTimeout = null;
    defaultReceivedTimeout = 3;
    defaultMinTimeout = 10;
    defaultMaxTimeout = 120;
    defaultTimeout = 60;
    TimeOutResponseError = () => {};
    TimeOutReceivedError = () => {};

    constructor(callback= () => {}, timeOutResponseError = () => {}, timeOutReceivedError = () => {}) {
        this.callback = callback;
        this.TimeOutResponseError = timeOutResponseError;
        this.TimeOutReceivedError = timeOutReceivedError;
    }
    closeConnection() {
        if (this.serialCom) this.serialCom.closePort();
    }
    async Procesar(data, segundosTimeout = this.defaultTimeout) {
        const config = JSON.parse(await PosConfig.GetPosConfig());
        const signedRequest = Utils.SignMessage(data);
        this.startReveivedTimeout();
        this.startTimeoutForResponse(segundosTimeout);
        if (config.IsUsbConnection) {
            this.CallSerial(signedRequest, config);
            return;
        }
        return this.IpComunication(signedRequest, config);
    }
    MensajeRecibido(jsonData) {
        if (jsonData.Received) {
            this.stopReceivedTimeout();
        }else {
            this.stopTimeoutForResponse();
        }
        this.callback(jsonData);
    }
    startTimeoutForResponse(segundos) {
        this.stopTimeoutForResponse();
        this.TimeoutForResponse = setTimeout(() => {
            this.TimeOutResponseError();
        }, segundos * 1000)
    }
    stopTimeoutForResponse () {
        if (this.TimeoutForResponse) {
            clearTimeout(this.TimeoutForResponse);
        }
    }
    startReveivedTimeout() {
        this.stopReceivedTimeout();
        this.ReceivedTimeout = setTimeout(() => {
            this.TimeOutReceivedError();
        }, this.defaultReceivedTimeout * 1000);
    }
    stopReceivedTimeout() {
        if (this.ReceivedTimeout){
            clearTimeout(this.ReceivedTimeout);
        }
    }
    CallSerial(signedRequest, config) {
        this.setSerialCom(config);
        this.serialCom.sendData(signedRequest, this);
    }
    setSerialCom(config) {
        if (!this.serialCom)
            this.serialCom = new SerialAgent(config);
    }
    setIpComunication(config) {
        if (!this.IpCom) {
            this.IpCom = new IpAgent(config);
            return;
        }
        if (!this.IpCom.conected){
            this.IpCom = null;
            this.setIpComunication(config);
        }
    }
    IpComunication(signedRequest, config) {
        try {
            this.setIpComunication(config);
            this.IpCom.sendData(signedRequest, this)
        } catch (error) {
            console.log('error')
            console.log(error)
            Utils.Log(error.message)
        }
    }
    Poll() {
        try {
            const data = new Requests.PollRequest(
                POSCommands.Function.Poll
                , new Date().toISOString()
            );
            this.Procesar(data, this.defaultMinTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.PollException(error.message);
        }
    }
    Sale(amount, ticket, printOnPos = false
        , saleType = POSCommands.SaleType.Sale, sendMessage = false
        , employeeId = 1, secondsTimeout = this.defaultMaxTimeout) {
        try {
            const data = new Requests.SaleRequest(
                POSCommands.Function.Sale
                , amount
                , ticket
                , printOnPos, saleType
                , sendMessage
                , employeeId
                , new Date().toISOString());
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.SaleException(error.message);
        }
    }
    LastVoucher(printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.LastVoucherRequest(
                POSCommands.Function.LastVoucher
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.LastVoucherException(error.message);
        }
    }
    Refund(operationId, printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.RefundRequest(
                POSCommands.Function.Refund
                , operationId
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.RefundException(error.message);
        }
    }
    Close(printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.CloseRequest(
                POSCommands.Function.Close
                , new Date().toISOString()
                , printOnPos
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.CloseException(error.message);
        }
    }
    Totals(printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.TotalsRequest(
                POSCommands.Function.Totals
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.TotalsException(error.message);
        }
    }
    Details(printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.DetailsRequest(
                POSCommands.Function.Details
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.DetailsException(error.message);
        }
    }
    SetNormalMode(secondsTimeout = this.defaultMinTimeout) {
        try {
            const data = new Requests.SetNormalModeRequest(
                POSCommands.Function.SetNormalMode
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.SetNormalModeException(error.message);
        }
    }
    Return(authorizationCode, amount, printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.ReturnRequest(
                POSCommands.Function.authorizationCode
                , authorizationCode
                , amount
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.ReturnException(error.message);
        }
    }
    DuplicateOthers(operationId, printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.DuplicateOthersRequest(
                POSCommands.Function.DuplicateOthers
                , operationId
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.DuplicateOthersException(error.message);
        }
    }
    SalesBySeller(employeeId, printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.SalesBySellerRequest(
                POSCommands.Function.SalesBySeller
                , employeeId
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.SalesBySellerException(error.message);
        }
    }
    TipReport(employeeId, printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.TipReportRequest(
                POSCommands.Function.TipReport
                , employeeId
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.TipReportException(error.message);
        }
    }
    DefaultSaleType(saleType, secondsTimeout = this.defaultMinTimeout) {
        try {
            const data = new Requests.DefaultSaleTypeRequest(
                POSCommands.Function.DefaultSaleType
                , saleType
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.DefaultSaleTypeException(error.message);
        }
    }
    ParameterReport(printOnPos = false, secondsTimeout = this.defaultTimeout) {
        try {
            const data = new Requests.ParameterReportRequest(
                POSCommands.Function.ParameterReport
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.ParameterReportException(error.message);
        }
    }
    SimReport(printOnPos = false, secondsTimeout = this.defaultMinTimeout) {
        try {
            const data = new Requests.SimReportRequest(
                POSCommands.Function.SimReport
                , printOnPos
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.SimReportException(error.message);
        }
    }
    CancelSale(secondsTimeout = this.defaultMinTimeout) {
        try {
            const data = new Requests.CancelSaleRequest(
                POSCommands.Function.CancelSale
                , new Date().toISOString()
            );
            this.Procesar(data, secondsTimeout);
        } catch (error) {
            Utils.Log(error.message);
            throw new exceptions.CancelSaleException(error.message);
        }
    }
}

module.exports = {
    POSIntegrado,
    getInstance
}