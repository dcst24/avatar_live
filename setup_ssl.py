"""
setup_ssl.py  –  Genera un certificado SSL auto-firmado para desarrollo local
                 y arranca el servidor con HTTPS.

Uso:
    python setup_ssl.py [--port 8010]

Requisitos (una sola vez):
    pip install cryptography

El certificado se guarda en:
    ssl/cert.pem
    ssl/key.pem

Luego arranca el servidor original (app.py) con SSL habilitado.
Accede desde: https://localhost:<port>/avatar.html
(El navegador mostrará una advertencia; haz clic en "Avanzado → Continuar")
"""

import argparse
import os
import sys
import ssl
import datetime

# ─── Generar certificado ───────────────────────────────────────────────────
def generate_cert(cert_path="ssl/cert.pem", key_path="ssl/key.pem"):
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import ipaddress
    except ImportError:
        print("[!] Falta la librería 'cryptography'. Instálala con:")
        print("       pip install cryptography")
        sys.exit(1)

    os.makedirs("ssl", exist_ok=True)

    if os.path.exists(cert_path) and os.path.exists(key_path):
        print(f"[✓] Certificado ya existe en {cert_path}")
        return cert_path, key_path

    print("[*] Generando clave privada RSA 2048…")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    print("[*] Generando certificado auto-firmado (válido 825 días)…")
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME,             "CL"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,        "Avatar Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME,              "localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Guardar clave privada
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Guardar certificado
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[✓] Certificado guardado → {cert_path}")
    print(f"[✓] Clave privada  guardada → {key_path}")
    return cert_path, key_path


# ─── Parchear app.py para usar SSL ────────────────────────────────────────
def patch_and_run(port: int, cert_path: str, key_path: str):
    """
    Importa app.py y lo arranca con SSL en TCPSite (aiohttp).
    Esta función sobreescribe temporalmente web.TCPSite para inyectar ssl_context.
    """
    import asyncio
    from aiohttp import web

    # Construir SSLContext
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(cert_path, key_path)

    # Monkey-patch: guardamos referencia original
    _OrigTCPSite = web.TCPSite

    class SSLTCPSite(_OrigTCPSite):
        """TCPSite que inyecta ssl_context automáticamente."""
        def __init__(self, runner, host=None, port=None, **kwargs):
            kwargs.setdefault("ssl_context", ssl_ctx)
            super().__init__(runner, host, port, **kwargs)

    web.TCPSite = SSLTCPSite

    # Ahora importamos y ejecutamos main() de app.py
    # Sobreescribimos el puerto si hace falta
    sys.argv = ["app.py", "--transport", "webrtc"]  # ajusta args según tu config
    print(f"\n{'='*55}")
    print(f"  Avatar HTTPS server  →  https://localhost:{port}/avatar.html")
    print(f"  Acepta la advertencia del navegador la primera vez.")
    print(f"{'='*55}\n")

    import app as avatar_app
    avatar_app.main()


# ─── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor avatar con HTTPS (dev)")
    parser.add_argument("--port",  type=int, default=8010, help="Puerto (default: 8010)")
    parser.add_argument("--cert",  default="ssl/cert.pem", help="Ruta al cert PEM")
    parser.add_argument("--key",   default="ssl/key.pem",  help="Ruta a la clave PEM")
    parser.add_argument("--only-cert", action="store_true",
                        help="Solo genera el certificado, no arranca el servidor")
    args = parser.parse_args()

    cert, key = generate_cert(args.cert, args.key)

    if args.only_cert:
        print("\n[i] Certificado listo. Para arrancarlo usa:")
        print(f"    python setup_ssl.py --port {args.port}")
    else:
        patch_and_run(args.port, cert, key)
