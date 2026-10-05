class CloseResponse {
    constructor(functionCode, responseCode, responseMessage, commerceCode, terminalId, success) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.CommerceCode = commerceCode;
        this.TerminalId = terminalId;
        this.Success = success;
    }
}

module.exports = CloseResponse;