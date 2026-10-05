class ConfigData {
    constructor(isUsbConnection, portName, baudRate, posIp, posPort) {
        this.IsUsbConnection = isUsbConnection;
        this.PortName = portName;
        this.BaudRate = baudRate;
        this.PosIp = posIp;
        this.PosPort = posPort;
    }
}

module.exports = ConfigData;
