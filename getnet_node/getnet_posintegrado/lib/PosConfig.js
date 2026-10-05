const fs = require('fs');
const crypto = require('crypto');

function GetPosConfig() {
  return new Promise(async (resolve, reject) => {
    try {
        const pathFile = "C:/Program Files/Getnet/pos.config";
        const data = fs.readFileSync(pathFile, 'utf-8');
        resolve(readPosConfig(data));
    }catch (ex) {
        throw new Error(ex.message);
    }
  });
}

function readPosConfig(data) {
    const key = data.substring(data.length - 16, data.length);
    return decriptData(data.substring(0, data.length - 16), key);
}

function decriptData(text, keyPass) {
  const encryptedTextParts = text.split(':');
    const iv = Buffer.from(encryptedTextParts[0], 'base64');
    const encryptedBytes = Buffer.from(encryptedTextParts[1], 'base64');
    const key = Buffer.from(keyPass, 'utf8');

    const decipher = crypto.createDecipheriv('aes-128-cbc', key, iv);
    let decrypted = decipher.update(encryptedBytes, 'base64', 'utf8');
    decrypted += decipher.final('utf8');

    return decrypted;
}


module.exports = {
    GetPosConfig
};