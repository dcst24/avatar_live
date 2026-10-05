class ParameterReportResponse {
    constructor(functionCode, responseCode, responseMessage, applicationName, version, so, emvModule, sn, model, communicationType, primaryIp, secondIp, company, apn, simId, sucursalId, terminalId, tip, ticket, employee, voucherAsTicket, returnVal, issuerQuotas, minimumIssuerQuotas, maximumIssuerQuotas, tradeQuotas, minimumTradeQuotas, maximumTradeQuotas, minimumAmount) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.ApplicationName = applicationName;
        this.Version = version;
        this.So = so;
        this.EmvModule = emvModule;
        this.Sn = sn;
        this.Model = model;
        this.CommunicationType = communicationType;
        this.PrimaryIp = primaryIp;
        this.SecondIp = secondIp;
        this.Company = company;
        this.Apn = apn;
        this.SimId = simId;
        this.SucursalId = sucursalId;
        this.TerminalId = terminalId;
        this.Tip = tip;
        this.Ticket = ticket;
        this.Employee = employee;
        this.VoucherAsTicket = voucherAsTicket;
        this.Return = returnVal;
        this.IssuerQuotas = issuerQuotas;
        this.MinimumIssuerQuotas = minimumIssuerQuotas;
        this.MaximumIssuerQuotas = maximumIssuerQuotas;
        this.TradeQuotas = tradeQuotas;
        this.MinimumTradeQuotas = minimumTradeQuotas;
        this.MaximumTradeQuotas = maximumTradeQuotas;
        this.MinimumAmount = minimumAmount;
    }
}

module.exports = ParameterReportResponse;