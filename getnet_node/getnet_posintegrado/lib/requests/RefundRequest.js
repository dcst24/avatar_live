class RefundRequest {
    constructor(command, operationId, printOnPos, dateTime) {
        this.Command = command;
        this.OperationId = operationId;
        this.PrintOnPos = printOnPos;
        this.DateTime = dateTime;
    }
}

module.exports = RefundRequest;
