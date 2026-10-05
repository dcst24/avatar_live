class PollResponse {
    constructor(functionCode, responseCode, responseMessage, connected) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.Connected = connected;
    }
}

module.exports = PollResponse;