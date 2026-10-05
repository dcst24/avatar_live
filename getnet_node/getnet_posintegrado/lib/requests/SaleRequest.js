class SaleRequest {
    constructor(command, amount, ticketNumber, printOnPos, saleType, sendMessage, employeeId, dateTime) {
        this.Command = command;
        this.Amount = amount;
        this.TicketNumber = ticketNumber;
        this.PrintOnPos = printOnPos;
        this.SaleType = saleType;
        this.SendMessage = sendMessage;
        this.EmployeeId = employeeId;
        this.DateTime = dateTime;
    }
}

module.exports = SaleRequest;