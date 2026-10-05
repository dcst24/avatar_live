class DuplicateOthersResponse {
    constructor(functionCode, responseCode, responseMessage, commerceCode, terminalId, ticket, authorizationCode, amount, sharesNumber, sharesAmount, last4Digits, operationId, cardType, accountingDate, accountNumber, cardBrand, realDate, employeeId, tip, saleType, posMode) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.CommerceCode = commerceCode;
        this.TerminalId = terminalId;
        this.Ticket = ticket;
        this.AuthorizationCode = authorizationCode;
        this.Amount = amount;
        this.SharesNumber = sharesNumber;
        this.SharesAmount = sharesAmount;
        this.Last4Digits = last4Digits;
        this.OperationId = operationId;
        this.CardType = cardType;
        this.AccountingDate = accountingDate;
        this.AccountNumber = accountNumber;
        this.CardBrand = cardBrand;
        this.RealDate = realDate;
        this.EmployeeId = employeeId;
        this.Tip = tip;
        this.SaleType = saleType;
        this.PosMode = posMode;
    }
}

module.exports = DuplicateOthersResponse;