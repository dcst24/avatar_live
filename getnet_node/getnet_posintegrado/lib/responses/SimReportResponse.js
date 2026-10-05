class SimReportResponse {
    constructor(functionCode, responseCode, responseMessage, connected, company, apnSim, apnConfig, simId, simProvider, simUsed, batteryPercentage, intensitySignal, rssi, simStatus, radioLevel, imei, networkConnection, networksEnabled, lac, callId, networkType, networkPlmn, simPlmn, networkLog) {
        this.FunctionCode = functionCode;
        this.ResponseCode = responseCode;
        this.ResponseMessage = responseMessage;
        this.Connected = connected;
        this.Company = company;
        this.ApnSim = apnSim;
        this.ApnConfig = apnConfig;
        this.SimId = simId;
        this.SimProvider = simProvider;
        this.SimUsed = simUsed;
        this.BatteryPercentage = batteryPercentage;
        this.IntensitySignal = intensitySignal;
        this.Rssi = rssi;
        this.SimStatus = simStatus;
        this.RadioLevel = radioLevel;
        this.Imei = imei;
        this.NetworkConnection = networkConnection;
        this.NetworksEnabled = networksEnabled;
        this.Lac = lac;
        this.CallId = callId;
        this.NetworkType = networkType;
        this.NetworkPlmn = networkPlmn;
        this.SimPlmn = simPlmn;
        this.NetworkLog = networkLog;
    }
}

module.exports = SimReportResponse;