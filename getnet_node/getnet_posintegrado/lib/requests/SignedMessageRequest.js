class SignedMessageRequest {
    constructor(jsonSerialized, sign) {
        this.JsonSerialized = jsonSerialized;
        this.Sign = sign;
    }
}

module.exports = SignedMessageRequest;