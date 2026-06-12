#!/bin/bash
# install_ca_mac.sh — Instalar CA del Avatar en macOS
# Copiar ssl/rootCA.pem al cliente primero.

CA="ssl/rootCA.pem"
[ ! -f "$CA" ] && { echo "ERROR: $CA no encontrado"; exit 1; }

echo "Instalando CA en macOS..."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CA"

if [ $? -eq 0 ]; then
    echo "CA instalada. Reinicia Safari/Chrome y abre:"
    echo "   https://SERVER_IP:8010/avatar.html"
else
    echo "Error: intenta ejecutar con sudo."
fi
