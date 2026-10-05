class ReturnRequest {
    constructor(command, authorizationCode, amount, printOnPos, dateTime) {
        this.Command = command;
        this.AuthorizationCode = authorizationCode;
        this.Amount = amount;
        this.PrintOnPos = printOnPos;
        this.DateTime = dateTime;
    }
}

module.exports = ReturnRequest;
