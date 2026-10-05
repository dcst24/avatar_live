const { SerialPort } = require('serialport');

class SerialAgent {
  constructor(config) {
    this.config = config;
    this.port = null;
    this.caller = null;
    this.start();
  }
  start() {
    this.port = new SerialPort({
      path: this.config.PortName,
      baudRate: this.config.BaudRate,
      highWaterMark: 1048576
    });
    this.port.on('data', (res) => {
      const jsonResponse = JSON.parse(res);
      if (jsonResponse.Received == undefined) {
        this.sendData(JSON.stringify({ Received: true }));
      }
      this.caller.MensajeRecibido(JSON.parse(res));
    });
    this.port.on('error', (err) => {
      console.error(err);
    });
  }
  async sendData(data, caller) {
    if (caller)
      this.caller = caller;
    this.port.write(data, err => {
      if (err) {
        console.error(err);
      }
    });
  }
  closePort() {
    if (this.port && this.port.isOpen) {
      this.port.close();
    }
  }
}
module.exports = {
  SerialAgent
}