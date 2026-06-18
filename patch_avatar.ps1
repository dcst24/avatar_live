$path = 'c:\Users\tom\Desktop\Proyectos\avatar_live\web\avatar.html'
$content = Get-Content $path -Encoding UTF8 -Raw

# ── Fix 1: DOMContentLoaded ─────────────────────────────────────────────────
# Remove the video.muted=false and _audioUnlocked=true from the desktop path
# and add Firefox detection

$oldDom = @'
window.addEventListener('DOMContentLoaded', () => {
    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    LOG('DOMContentLoaded - isMobile:', isMobile);
    LOG('Secure context:', window.isSecureContext, '| location.protocol:', location.protocol);

    if (!window.isSecureContext) {
        WARN('? CONTEXTO NO SEGURO (HTTP). SpeechRecognition NO funcionara. Usar HTTPS.');
    }

    if (isMobile) {
        LOG('Mobile detectado  esperando tap del usuario (overlay visible)');
        // nada - el overlay espera el tap
    } else {
        LOG('Desktop detectado  auto-conectando');
        const overlay = document.getElementById('tap-overlay');
        if (overlay) overlay.style.display = 'none';
        document.getElementById('video').muted = false;
        _audioUnlocked = true;
        setTimeout(connectRTC, 800);
    }
});
'@

$newDom = @'
window.addEventListener('DOMContentLoaded', () => {
    const isMobile  = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const isFirefox = /Firefox\//.test(navigator.userAgent);

    LOG('DOMContentLoaded - isMobile:', isMobile, '| isFirefox:', isFirefox);
    LOG('Secure context:', window.isSecureContext, '| protocol:', location.protocol);

    if (!window.isSecureContext) {
        WARN('CONTEXTO NO SEGURO (HTTP). SpeechRecognition NO funcionara. Usar HTTPS.');
    }

    if (isFirefox) {
        // Firefox elimino SpeechRecognition en v56+. _useFallbackASR ya es true.
        WARN('Firefox detectado: SpeechRecognition NO disponible en Firefox.');
        WARN('Para usar el microfono usa Chrome, Chromium o Edge.');
    }

    if (isMobile) {
        LOG('Mobile detectado - overlay visible, esperando tap');
    } else {
        LOG('Desktop detectado - auto-conectando. Video inicia muted (se desmuta al pulsar el mic)');
        const overlay = document.getElementById('tap-overlay');
        if (overlay) overlay.style.display = 'none';
        // NO seteamos video.muted=false aqui: Chromium bloquea autoplay con sonido
        // sin gesto del usuario. El video arranca muted y se desmuta al pulsar el mic.
        setTimeout(connectRTC, 800);
    }
});
'@

# We need to do a byte-level comparison to handle encoding issues.
# Instead, let's target specific unique lines.
# Replace line 1272: document.getElementById('video').muted = false;
# Replace line 1273: _audioUnlocked = true;
# And add Firefox detection

$lines = Get-Content $path -Encoding UTF8
$totalLines = $lines.Count
Write-Host "Total lines: $totalLines"

# Find the DOMContentLoaded block
$domIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "window\.addEventListener\('DOMContentLoaded'") {
        $domIdx = $i
        Write-Host "Found DOMContentLoaded at line $($i+1)"
        break
    }
}

if ($domIdx -lt 0) {
    Write-Host "ERROR: DOMContentLoaded not found"
    exit 1
}

# Build new block
$newBlock = @(
    "window.addEventListener('DOMContentLoaded', () => {",
    "    const isMobile  = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);",
    "    const isFirefox = /Firefox\//.test(navigator.userAgent);",
    "",
    "    LOG('DOMContentLoaded - isMobile:', isMobile, '| isFirefox:', isFirefox);",
    "    LOG('Secure context:', window.isSecureContext, '| protocol:', location.protocol);",
    "",
    "    if (!window.isSecureContext) {",
    "        WARN('CONTEXTO NO SEGURO (HTTP). SpeechRecognition NO funcionara. Usar HTTPS.');",
    "    }",
    "",
    "    if (isFirefox) {",
    "        // Firefox elimino SpeechRecognition en v56+. _useFallbackASR ya es true.",
    "        WARN('Firefox detectado: SpeechRecognition NO disponible en Firefox.');",
    "        WARN('Para usar el microfono usa Chrome, Chromium o Edge.');",
    "    }",
    "",
    "    if (isMobile) {",
    "        LOG('Mobile detectado - overlay visible, esperando tap');",
    "    } else {",
    "        LOG('Desktop detectado - auto-conectando. Video inicia muted (se desmuta al pulsar el mic)');",
    "        const overlay = document.getElementById('tap-overlay');",
    "        if (overlay) overlay.style.display = 'none';",
    "        // NO seteamos video.muted=false: Chromium bloquea autoplay con sonido sin gesto.",
    "        // El video arranca muted y se desmuta cuando el usuario pulsa el mic.",
    "        setTimeout(connectRTC, 800);",
    "    }",
    "});"
)

# Find the end of the DOMContentLoaded block (the closing });)
$domEnd = -1
for ($i = $domIdx + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\}\);$") {
        $domEnd = $i
        Write-Host "Found closing at line $($i+1)"
        break
    }
}

if ($domEnd -lt 0) {
    Write-Host "ERROR: closing }); not found"
    exit 1
}

# Replace the block
$newLines = @()
for ($i = 0; $i -lt $domIdx; $i++) {
    $newLines += $lines[$i]
}
foreach ($l in $newBlock) {
    $newLines += $l
}
for ($i = $domEnd + 1; $i -lt $lines.Count; $i++) {
    $newLines += $lines[$i]
}

# ── Fix 2: connectRTC - add video play polling ──────────────────────────────
# Find connectRTC function
$rtcIdx = -1
for ($i = 0; $i -lt $newLines.Count; $i++) {
    if ($newLines[$i] -match "^function connectRTC\(\)") {
        $rtcIdx = $i
        Write-Host "Found connectRTC at line $($i+1)"
        break
    }
}

if ($rtcIdx -lt 0) {
    Write-Host "ERROR: connectRTC not found"
    exit 1
}

# Find the setTimeout inside connectRTC (the one with btn-mic)
$rtcSetTimeout = -1
for ($i = $rtcIdx; $i -lt $newLines.Count; $i++) {
    if ($newLines[$i] -match "setTimeout.*=>") {
        $rtcSetTimeout = $i
        Write-Host "Found setTimeout in connectRTC at line $($i+1)"
        break
    }
}

# Insert video play polling before the setTimeout
$videoPolling = @(
    "",
    "    // FIX AUTOPLAY LINUX/UBUNTU: vigilar cuando el stream llega al video y forzar play() muted.",
    "    // Chromium bloquea autoplay con sonido, pero permite muted. El audio se desbloquea al pulsar el mic.",
    "    const _v = document.getElementById('video');",
    "    let _vChecks = 0;",
    "    const _vTimer = setInterval(function() {",
    "        _vChecks++;",
    "        if (_v.srcObject) {",
    "            if (_v.paused) {",
    "                _v.muted = true;",
    "                _v.play()",
    "                    .then(function() { LOG('video.play() OK muted - audio se activa al pulsar el mic'); clearInterval(_vTimer); })",
    "                    .catch(function(e) { WARN('video.play() muted fallo:', e.name); clearInterval(_vTimer); });",
    "            } else {",
    "                LOG('Video reproduciendo (srcObject listo, paused=false)');",
    "                clearInterval(_vTimer);",
    "            }",
    "        } else if (_vChecks > 30) {",
    "            WARN('15s sin stream en el video. Verifica WebRTC (codec VP8/H264) o la red.');",
    "            clearInterval(_vTimer);",
    "        }",
    "    }, 500);"
)

$finalLines = @()
for ($i = 0; $i -lt $rtcSetTimeout; $i++) {
    $finalLines += $newLines[$i]
}
foreach ($l in $videoPolling) {
    $finalLines += $l
}
for ($i = $rtcSetTimeout; $i -lt $newLines.Count; $i++) {
    $finalLines += $newLines[$i]
}

# Write back with UTF8 BOM-less
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$joined = $finalLines -join "`r`n"
[System.IO.File]::WriteAllText($path, $joined, $utf8NoBom)

Write-Host "Done! File written with $($finalLines.Count) lines."
