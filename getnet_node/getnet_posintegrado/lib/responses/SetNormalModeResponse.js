class SetNormalModeResponse {
    constructor(functionCode, responseCode, responseMessage, changeToNormalMode) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.ChangeToNormalMode = changeToNormalMode;
    }
}

module.exports = SetNormalModeResponse;