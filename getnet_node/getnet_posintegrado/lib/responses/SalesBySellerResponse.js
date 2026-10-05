class SalesBySellerResponse {
    constructor(functionCode, responseCode, responseMessage, saleDetails) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.SaleDetails = saleDetails;
    }
}

module.exports = SalesBySellerResponse;