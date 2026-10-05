class SalesBySellerRequest {
    constructor(command, employeeId, printOnPos, dateTime) {
        this.Command = command;
        this.EmployeeId = employeeId;
        this.PrintOnPos = printOnPos;
        this.DateTime = dateTime;
    }
}

module.exports = SalesBySellerRequest;
