class DetailsRequest {
    constructor(command, printOnPos, dateTime) {
        this.Command = command;
        this.PrintOnPos = printOnPos;
        this.DateTime = dateTime;
    }
}

module.exports = DetailsRequest;
