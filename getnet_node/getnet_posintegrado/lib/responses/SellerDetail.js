class SellerDetail {
    constructor(date, employeeId, ticket, amount, nc, tc, tx) {
        this.Date = date;
        this.EmployeeId = employeeId;
        this.Ticket = ticket;
        this.Amount = amount;
        this.Nc = nc;
        this.Tc = tc;
        this.Tx = tx;
    }
}

module.exports = SellerDetail;