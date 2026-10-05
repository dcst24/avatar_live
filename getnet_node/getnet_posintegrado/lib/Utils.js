const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

function SignMessage(data) {
  try {
    var jsonSerialized = JSON.stringify(data);
    var sign = signWithSha256(jsonSerialized);
    var signedData = {
      JsonSerialized: jsonSerialized,
      Sign: sign.toUpperCase()
    };
    return JSON.stringify(signedData);
  } catch (ex) {
    throw new Error(ex.message);
  }
}
function signWithSha256(jsonMessage) {
  try {
    return crypto.createHash('sha256')
      .update(jsonMessage)
      .digest('hex');
  } catch (ex) {
    throw new Error(ex.message);
  }
}
function Log(logs) {
  try {
    const currentDate = new Date();
    const month = currentDate.getMonth() + 1;
    const root = "./logs";
    const yearPath = path.join(root, currentDate.getFullYear().toString());
    const monthPath = path.join(yearPath, month.toString().padStart(2, '0'));
    const formattedDate = currentDate
      .toLocaleDateString('es-ES', { year: 'numeric', month: '2-digit', day: '2-digit' })
      .replace(/\//g, '-');
    const logFile = path.join(monthPath, "Logs-" + formattedDate + ".txt");
    if (!fs.existsSync(monthPath)) {
      fs.mkdirSync(monthPath, { recursive: true });
    }
    let log = "--- " + currentDate.toString() + " ---\n";
    log += evaluarLog(logs);
    log += "\n---------------------------\n";
    fs.appendFileSync(logFile, log);
  } catch (error) {
    console.error(error);
  }
}
const evaluarLog = (logs) => {
  if (!logs.includes('{'))
    return "ERROR: " + logs;
  if (logs.includes('Sign'))
      return "REQUEST: " + logs
  return "RESPONSE: " + logs
}


module.exports = {
  SignMessage,
  signWithSha256,
  Log
}