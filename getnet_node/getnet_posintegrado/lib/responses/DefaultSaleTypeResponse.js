class DefaultSaleTypeResponse {
    constructor(functionCode, responseCode, responseMessage, saleType) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.SaleType = saleType;
    }
}

module.exports = DefaultSaleTypeResponse;