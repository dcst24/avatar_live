const { Socket } = require('net');

class IpAgent {
    caller = null;
    conected = false;
    constructor(config) {
        this.client = new Socket();
        this.host = config.PosIp;
        this.port = config.PosPort;
        this.client.connect(this.port, this.host, () => {
            console.log('conectado');
            this.conected = true;
        });
        this.client.on('data', (data) => {
            this.caller.MensajeRecibido(JSON.parse(data));
        });
        this.client.on('error', err => {
            console.log(err);
        });
        this.client.on('close', () => {
            console.log('Conexión cerrada');
            this.conected = false;
        });
    }
    sendData(jsonSerialized, caller) {
        this.caller = caller;
        this.client.write(jsonSerialized);
    }
}

module.exports = {
    IpAgent
}