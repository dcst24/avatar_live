class CancelSaleResponse {
    constructor(functionCode, responseCode, responseMessage) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
    }
}

module.exports = CancelSaleResponse;