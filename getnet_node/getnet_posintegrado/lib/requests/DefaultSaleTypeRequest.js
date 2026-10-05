class DefaultSaleTypeRequest {
    constructor(command, saleType, dateTime) {
        this.Command = command;
        this.SaleType = saleType;
        this.DateTime = dateTime;
    }
}

module.exports = DefaultSaleTypeRequest;
