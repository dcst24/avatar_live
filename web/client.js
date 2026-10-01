var pc = null;

function negotiate() {
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });
    return pc.createOffer().then((offer) => {
        return pc.setLocalDescription(offer);
    }).then(() => {
        // wait for ICE gathering to complete
        return new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                const checkState = () => {
                    if (pc.iceGatheringState === 'complete') {
                        pc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                };
                pc.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(() => {
        var offer = pc.localDescription;
        return fetch('/offer', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then((response) => {
        return response.json();
    }).then((answer) => {
        document.getElementById('sessionid').value = answer.sessionid
        return pc.setRemoteDescription(answer);
    }).catch((e) => {
        alert(e);
    });
}

function start() {
    var config = {
        sdpSemantics: 'unified-plan'
    };

    if (document.getElementById('use-stun').checked) {
        config.iceServers = [{ urls: ['stun:stun.l.google.com:19302'] }];
    }

    pc = new RTCPeerConnection(config);

    // connect audio / video
    // IMPORTANTE: ambos tracks (audio + video) van al mismo elemento <video>.
    // El video empieza con muted=true en el HTML (permite autoplay en Android sin gesto).
    // handleTapToStart() en avatar.html desmutea tras el primer tap del usuario.
    let _remoteStream = null;
    pc.addEventListener('track', (evt) => {
        const videoEl = document.getElementById('video');
        if (evt.streams && evt.streams[0]) {
            if (!_remoteStream) {
                _remoteStream = evt.streams[0];
                videoEl.srcObject = _remoteStream;
            } else if (videoEl.srcObject !== evt.streams[0]) {
                _remoteStream.addTrack(evt.track);
            }
        } else {
            if (!_remoteStream) {
                _remoteStream = new MediaStream();
                videoEl.srcObject = _remoteStream;
            }
            _remoteStream.addTrack(evt.track);
        }
        videoEl.play().catch(err => {
            console.warn('[WebRTC] play() rechazado:', err.name, '-', err.message);
        });
    });

    document.getElementById('start').style.display = 'none';
    negotiate();
    document.getElementById('stop').style.display = 'inline-block';
}

function stop() {
    document.getElementById('stop').style.display = 'none';

    // close peer connection
    setTimeout(() => {
        pc.close();
    }, 500);
}

window.addEventListener('pagehide', function(event) {
    try {
        if (typeof pc !== 'undefined' && pc && pc.close) {
            pc.close();
        }
    } catch (_) {}
});