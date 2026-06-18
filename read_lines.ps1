$lines = Get-Content 'c:\Users\tom\Desktop\Proyectos\avatar_live\web\avatar.html' -Encoding UTF8
# Print connectRTC section
Write-Host "=== connectRTC ==="
for ($i = 700; $i -lt 760; $i++) {
    Write-Host ($i.ToString() + ': ' + $lines[$i])
}
Write-Host ""
Write-Host "=== DOMContentLoaded ==="
for ($i = 1280; $i -lt [Math]::Min(1309, $lines.Count); $i++) {
    Write-Host ($i.ToString() + ': ' + $lines[$i])
}
