class POSCommands {
    static Function = {
        Sale: 100,
        LastVoucher: 101,
        Refund: 102,
        Close: 103,
        Totals: 104,
        Details: 105,
        Poll: 106,
        SetNormalMode: 107,
        Return: 108,
        DuplicateOthers: 109,
        SalesBySeller: 110,
        TipReport: 111,
        AlternativeSaleExemptedAffects: 112,
        DefaultSaleType: 113,
        ParameterReport: 114,
        SimReport: 115,
        CancelSale: 116
    };
    static SaleType = {
        Sale: 0,
        SaleAffects: 1,
        InvoiceAffects: 2,
        SaleExempted: 3,
        InvoiceExempted: 4,
        CollectionAffects: 5,
        CollectionExempted: 6
    };
}
module.exports = POSCommands;