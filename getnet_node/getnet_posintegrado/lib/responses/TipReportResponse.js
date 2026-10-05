class TipReportResponse {
    constructor(functionCode, responseCode, responseMessage, tipReport) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.TipReport = tipReport;
    }
}

module.exports = TipReportResponse;