#!/bin/bash
# install_ca_linux.sh — Instalar CA del Avatar en Linux
# Copiar ssl/rootCA.pem al cliente primero.

CA="ssl/rootCA.pem"
[ ! -f "$CA" ] && { echo "ERROR: $CA no encontrado"; exit 1; }

echo "Instalando CA en Linux..."
if command -v update-ca-certificates &>/dev/null; then
    sudo cp "$CA" /usr/local/share/ca-certificates/avatar_local_ca.crt
    sudo update-ca-certificates
elif command -v trust &>/dev/null; then
    sudo trust anchor --store "$CA"
else
    echo "Instala ca-certificates y vuelve a intentar."
    exit 1
fi

# Para Chrome/Chromium en Linux (usa NSS)
if command -v certutil &>/dev/null; then
    for db in ~/.pki/nssdb ~/.mozilla/firefox/*.default*/; do
        [ -d "$db" ] && certutil -A -d "sql:$db" -n "Avatar Local CA" -t "CT,," -i "$CA" 2>/dev/null
    done
fi
echo "Listo. Reinicia el navegador y abre:"
echo "   https://SERVER_IP:8010/avatar.html"
