class TipReport {
    constructor(employeeId, tx, sales, tips) {
        this.EmployeeId = employeeId;
        this.Tx = tx;
        this.Sales = sales;
        this.Tips = tips;
    }
}

module.exports = TipReport;
