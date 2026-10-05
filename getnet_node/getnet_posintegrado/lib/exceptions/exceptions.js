class CancelSaleException extends Error {
    constructor(message) {
        super(message);
        this.name = "CancelSaleException";
    }
}
class PollException extends Error {
    constructor(message) {
        super(message);
        this.name = "PollException";
    }
}
class CloseException extends Error {
    constructor(message) {
        super(message);
        this.name = "CloseException";
    }
}
class CustomException extends Error {
    constructor(message) {
        super(message);
        this.name = "CustomException";
    }
}
class DefaultSaleTypeException extends Error {
    constructor(message) {
        super(message);
        this.name = "DefaultSaleTypeException";
    }
}
class DetailsException extends Error {
    constructor(message) {
        super(message);
        this.name = "DefaultSaleTypeException";
    }
}
class DuplicateOthersException extends Error {
    constructor(message) {
        super(message);
        this.name = "DuplicateOthersException";
    }
}
class LastVoucherException extends Error {
    constructor(message) {
        super(message);
        this.name = "LastSaleException";
    }
}
class ParameterReportException extends Error {
    constructor(message) {
        super(message);
        this.name = "ParameterReportException";
    }
}
class RefundException extends Error {
    constructor(message) {
        super(message);
        this.name = "RefundException";
    }
}
class ReturnException extends Error {
    constructor(message) {
        super(message);
        this.name = "ReturnException";
    }
}
class SaleException extends Error {
    constructor(message) {
        super(message);
        this.name = "SaleException";
    }
}
class SalesBySellerException extends Error {
    constructor(message) {
        super(message);
        this.name = "SalesBySellerException";
    }
}
class SimReportException extends Error {
    constructor(message) {
        super(message);
        this.name = "SimReportException";
    }
}
class TipReportException extends Error {
    constructor(message) {
        super(message);
        this.name = "TipReportException";
    }
}
class TotalsException extends Error {
    constructor(message) {
        super(message);
        this.name = "TotalsException";
    }
}
class SetNormalModeException extends Error {
    constructor(message) {
        super(message);
        this.name = "SetNormalModeException";
    }
}

module.exports = {
    CancelSaleException,
    CloseException,
    CustomException,
    DefaultSaleTypeException,
    DetailsException,
    DuplicateOthersException,
    LastVoucherException,
    ParameterReportException,
    RefundException,
    ReturnException,
    SaleException,
    SalesBySellerException,
    SimReportException,
    TipReportException,
    TotalsException,
    PollException,
    SetNormalModeException
}