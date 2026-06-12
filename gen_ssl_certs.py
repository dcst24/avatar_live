"""
gen_ssl_certs.py
================
Genera una CA propia + certificado de servidor firmado por esa CA.
El certificado cubre TODAS las IPs de red local del equipo y también
localhost / 127.0.0.1, por lo que el avatar puede abrirse desde
CUALQUIER PC de la red con solo instalar la CA.

Uso:
    python gen_ssl_certs.py [--port 8010]

Archivos generados en ssl/:
    rootCA.pem          ← Instalar en cada cliente (solo 1 vez)
    rootCA-key.pem      ← Clave privada de la CA (guardar en el servidor)
    server.pem          ← Certificado del servidor
    server-key.pem      ← Clave privada del servidor

Instalar la CA en clientes:
    Windows:  install_ca.ps1   (PowerShell como Administrador)
    Linux:    install_ca_linux.sh
    macOS:    install_ca_mac.sh
"""

import datetime
import ipaddress
import os
import socket
import sys
import argparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

SSL_DIR = os.path.join(os.path.dirname(__file__), "ssl")

# ─── Detectar IPs locales ─────────────────────────────────────────────────────

def get_local_ips() -> list[str]:
    """Devuelve todas las IPs IPv4 no-loopback del equipo."""
    ips = set()
    try:
        # Método principal: conectar a DNS de Google (sin enviar datos)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except Exception:
        pass

    # Método de respaldo: enumerar todas las interfaces
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            family, _, _, _, sockaddr = info
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if not ip.startswith("127."):
                    ips.add(ip)
    except Exception:
        pass

    return sorted(ips)

# ─── Generar clave privada RSA ────────────────────────────────────────────────

def gen_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)

# ─── Guardar archivos PEM ─────────────────────────────────────────────────────

def save_key(key, path: str, password: bytes | None = None):
    enc = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    with open(path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=enc,
        ))
    print(f"  [OK] {path}")


def save_cert(cert, path: str):
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"  [OK] {path}")

# ─── Crear la CA raíz ─────────────────────────────────────────────────────────

def create_ca():
    key = gen_key()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,    "Avatar LiveTalking Local CA"),
        x509.NameAttribute(NameOID.COMMON_NAME,          "Avatar LiveTalking Root CA"),
        x509.NameAttribute(NameOID.COUNTRY_NAME,         "CL"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))   # 10 años
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert

# ─── Crear certificado de servidor firmado por la CA ─────────────────────────

def create_server_cert(ca_key, ca_cert, extra_ips: list[str]):
    key = gen_key()

    local_ips = get_local_ips()
    all_ips = sorted(set(local_ips + extra_ips))

    print(f"\n  IPs incluidas en el certificado:")
    for ip in all_ips:
        print(f"    - {ip}")
    print(f"    - 127.0.0.1")
    print(f"    - ::1  (IPv6 loopback)")

    san_list = [
        x509.DNSName("localhost"),
    ]
    for ip in all_ips:
        try:
            san_list.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            print(f"  [!] IP inválida ignorada: {ip}")
    san_list.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    san_list.append(x509.IPAddress(ipaddress.ip_address("::1")))

    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Avatar LiveTalking"),
        x509.NameAttribute(NameOID.COMMON_NAME,       "Avatar Server"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))  # ~2 años (límite de browsers)
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert

# ─── Crear scripts de instalación de la CA para clientes ─────────────────────

def write_client_scripts(ca_pem_path: str, port: int):
    rel_ca = "ssl\\rootCA.pem"

    # Windows PowerShell
    ps_path = os.path.join(os.path.dirname(__file__), "install_ca.ps1")
    ps_content = f"""# install_ca.ps1 — Instalar CA del Avatar en Windows (ejecutar como Administrador)
# Necesario para que Chrome/Edge/Firefox confíen en el certificado HTTPS
# y el micrófono funcione desde cualquier PC de la red.

param(
    [string]$ServerIP = "192.168.0.73"
)

$caFile = Join-Path $PSScriptRoot "{rel_ca}"

if (-not (Test-Path $caFile)) {{
    Write-Error "No se encontro ssl\\rootCA.pem. Copia el proyecto primero."
    exit 1
}}

Write-Host ""
Write-Host "Instalando CA del Avatar en el almacen de confianza del sistema..." -ForegroundColor Cyan
certutil -addstore -f "ROOT" $caFile

if ($LASTEXITCODE -eq 0) {{
    Write-Host ""
    Write-Host "CA instalada correctamente." -ForegroundColor Green
    Write-Host "Reinicia Chrome/Edge si ya estaba abierto." -ForegroundColor Yellow
    Write-Host "Luego abre desde cualquier PC:" -ForegroundColor White
    Write-Host "   https://${{ServerIP}}:{port}/avatar.html" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "IPs disponibles del servidor:" -ForegroundColor White
    {chr(10).join(f'    Write-Host "   https://{ip}:{port}/avatar.html"' for ip in get_local_ips())}
}} else {{
    Write-Host "Hubo un error. Ejecuta PowerShell como Administrador." -ForegroundColor Red
}}
"""
    with open(ps_path, "w", encoding="utf-8") as f:
        f.write(ps_content)
    print(f"  [OK] {ps_path}")

    # Linux bash
    sh_path = os.path.join(os.path.dirname(__file__), "install_ca_linux.sh")
    sh_content = f"""#!/bin/bash
# install_ca_linux.sh — Instalar CA del Avatar en Linux
# Copiar ssl/rootCA.pem al cliente primero.

CA="ssl/rootCA.pem"
[ ! -f "$CA" ] && {{ echo "ERROR: $CA no encontrado"; exit 1; }}

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
echo "   https://SERVER_IP:{port}/avatar.html"
"""
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write(sh_content)
    print(f"  [OK] {sh_path}")

    # macOS
    mac_path = os.path.join(os.path.dirname(__file__), "install_ca_mac.sh")
    mac_content = f"""#!/bin/bash
# install_ca_mac.sh — Instalar CA del Avatar en macOS
# Copiar ssl/rootCA.pem al cliente primero.

CA="ssl/rootCA.pem"
[ ! -f "$CA" ] && {{ echo "ERROR: $CA no encontrado"; exit 1; }}

echo "Instalando CA en macOS..."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CA"

if [ $? -eq 0 ]; then
    echo "CA instalada. Reinicia Safari/Chrome y abre:"
    echo "   https://SERVER_IP:{port}/avatar.html"
else
    echo "Error: intenta ejecutar con sudo."
fi
"""
    with open(mac_path, "w", encoding="utf-8") as f:
        f.write(mac_content)
    print(f"  [OK] {mac_path}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generar certificados SSL para el avatar")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--extra-ip", nargs="*", default=[], metavar="IP",
                        help="IPs adicionales a incluir en el certificado")
    parser.add_argument("--force", action="store_true",
                        help="Regenerar CA aunque ya exista (invalida clientes instalados)")
    args = parser.parse_args()

    os.makedirs(SSL_DIR, exist_ok=True)

    ca_cert_path = os.path.join(SSL_DIR, "rootCA.pem")
    ca_key_path  = os.path.join(SSL_DIR, "rootCA-key.pem")
    srv_cert_path = os.path.join(SSL_DIR, "server.pem")
    srv_key_path  = os.path.join(SSL_DIR, "server-key.pem")

    # ── CA ──────────────────────────────────────────────────────────────────
    if args.force or not os.path.exists(ca_cert_path):
        print("\n[1/2] Generando CA raiz...")
        ca_key, ca_cert = create_ca()
        save_key(ca_key, ca_key_path)
        save_cert(ca_cert, ca_cert_path)
        print("      ATENCION: CA nueva generada — los clientes deben reinstalar install_ca.ps1")
    else:
        print("\n[1/2] Usando CA existente (ssl/rootCA.pem). Usa --force para regenerar.")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.x509 import load_pem_x509_certificate
        with open(ca_key_path, "rb") as f:
            ca_key = load_pem_private_key(f.read(), password=None)
        with open(ca_cert_path, "rb") as f:
            ca_cert = load_pem_x509_certificate(f.read())

    # ── Certificado de servidor ──────────────────────────────────────────────
    print("\n[2/2] Generando certificado de servidor...")
    srv_key, srv_cert = create_server_cert(ca_key, ca_cert, args.extra_ip)
    save_key(srv_key, srv_key_path)
    save_cert(srv_cert, srv_cert_path)

    # ── Scripts de clientes ──────────────────────────────────────────────────
    print("\n[+] Actualizando scripts de instalacion de clientes...")
    write_client_scripts(ca_cert_path, args.port)

    local_ips = get_local_ips()
    print("\n" + "=" * 60)
    print("  LISTO. Pasos para activar:")
    print()
    print("  1. Arrancar el servidor:")
    print("     python setup_ssl.py --cert ssl/server.pem --key ssl/server-key.pem")
    print()
    print("  2. En CADA PC cliente (solo 1 vez), copiar esta carpeta y ejecutar:")
    print("     PowerShell (Administrador) > .\\install_ca.ps1")
    print()
    print("  3. Abrir el avatar desde cualquier PC:")
    for ip in local_ips:
        print(f"     https://{ip}:8010/avatar.html")
    print("=" * 60)


if __name__ == "__main__":
    main()
