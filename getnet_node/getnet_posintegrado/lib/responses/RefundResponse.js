class RefundResponse {
    constructor(functionCode, responseCode, responseMessage, commerceCode, terminalId, authorizationCode, operationId, success) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.CommerceCode = commerceCode;
        this.TerminalId = terminalId;
        this.AuthorizationCode = authorizationCode;
        this.OperationId = operationId;
        this.Success = success;
    }
}

module.exports = RefundResponse;