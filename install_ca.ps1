# install_ca.ps1 — Instalar CA del Avatar en Windows (ejecutar como Administrador)
# Necesario para que Chrome/Edge/Firefox confíen en el certificado HTTPS
# y el micrófono funcione desde cualquier PC de la red.

param(
    [string]$ServerIP = "192.168.0.73"
)

$caFile = Join-Path $PSScriptRoot "ssl\rootCA.pem"

if (-not (Test-Path $caFile)) {
    Write-Error "No se encontro ssl\rootCA.pem. Copia el proyecto primero."
    exit 1
}

Write-Host ""
Write-Host "Instalando CA del Avatar en el almacen de confianza del sistema..." -ForegroundColor Cyan
certutil -addstore -f "ROOT" $caFile

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "CA instalada correctamente." -ForegroundColor Green
    Write-Host "Reinicia Chrome/Edge si ya estaba abierto." -ForegroundColor Yellow
    Write-Host "Luego abre desde cualquier PC:" -ForegroundColor White
    Write-Host "   https://${ServerIP}:8010/avatar.html" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "IPs disponibles del servidor:" -ForegroundColor White
        Write-Host "   https://192.168.0.211:8010/avatar.html"
    Write-Host "   https://192.168.0.73:8010/avatar.html"
    Write-Host "   https://192.168.1.211:8010/avatar.html"
} else {
    Write-Host "Hubo un error. Ejecuta PowerShell como Administrador." -ForegroundColor Red
}
