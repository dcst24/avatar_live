class CloseRequest {
    constructor(command, dateTime, PrintOnPos) {
        this.Command = command;
        this.DateTime = dateTime;
        this.PrintOnPos = PrintOnPos;
    }
}
module.exports = CloseRequest;