# install_ca.ps1
# Ejecutar en el PC cliente (con PowerShell como Administrador)
# Instala la CA de mkcert del servidor para que el browser confíe en el certificado SSL
# y el microfono funcione desde https://192.168.0.72:<puerto>/avatar.html

$caFile = Join-Path $PSScriptRoot "ssl\rootCA.pem"

if (-not (Test-Path $caFile)) {
    Write-Error "No se encontró ssl\rootCA.pem. Asegúrate de haber hecho git pull primero."
    exit 1
}

Write-Host "`n🔒 Instalando CA de mkcert en el almacen de confianza del sistema..." -ForegroundColor Cyan
certutil -addstore -f "ROOT" $caFile

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ CA instalada correctamente." -ForegroundColor Green
    Write-Host "   Reinicia Chrome/Edge si ya estaba abierto." -ForegroundColor Yellow
    Write-Host "   Luego abre: https://192.168.0.72:8010/avatar.html" -ForegroundColor White
} else {
    Write-Host "`n❌ Hubo un error. Asegurate de ejecutar PowerShell como Administrador." -ForegroundColor Red
}
