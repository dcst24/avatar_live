"""
setup_ssl.py  –  Arranca el servidor con HTTPS usando certificado mkcert
                 (confiable por el sistema, sin advertencias del navegador)

Prerequisitos (ya instalados):
    mkcert ya instalado y CA registrada.
    Los certificados están en ssl/localhost+2.pem y ssl/localhost+2-key.pem

Uso:
    python setup_ssl.py [--port 8010]

Accede desde:
    https://localhost:<port>/avatar.html

El micrófono funcionará directamente (HTTPS seguro sin advertencias).
"""

import argparse
import os
import sys
import ssl

# Rutas de los certificados generados por mkcert
DEFAULT_CERT = os.path.join(os.path.dirname(__file__), "ssl", "localhost+2.pem")
DEFAULT_KEY  = os.path.join(os.path.dirname(__file__), "ssl", "localhost+2-key.pem")


def check_certs(cert_path: str, key_path: str):
    """Verifica que los certificados existen, si no da instrucciones."""
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("[!] No se encontraron los certificados mkcert.")
        print("    Genera el certificado ejecutando una vez:")
        print()
        print("       mkcert -install")
        print('       mkcert localhost 127.0.0.1 ::1')
        print(f"       move localhost+2.pem {cert_path}")
        print(f"       move localhost+2-key.pem {key_path}")
        print()
        sys.exit(1)
    print(f"[✓] Certificado : {cert_path}")
    print(f"[✓] Clave privada: {key_path}")


def patch_and_run(port: int, cert_path: str, key_path: str):
    """
    Importa app.py y lo arranca con SSL en TCPSite (aiohttp).
    Monkey-patchea web.TCPSite para inyectar ssl_context automáticamente.
    """
    import asyncio
    from aiohttp import web

    # Construir SSLContext con los certificados mkcert
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(cert_path, key_path)

    # Guardar referencia original de TCPSite
    _OrigTCPSite = web.TCPSite

    class SSLTCPSite(_OrigTCPSite):
        """TCPSite que inyecta ssl_context de mkcert automáticamente."""
        def __init__(self, runner, host=None, port=None, **kwargs):
            kwargs.setdefault("ssl_context", ssl_ctx)
            super().__init__(runner, host, port, **kwargs)

    web.TCPSite = SSLTCPSite

    print()
    print("=" * 60)
    print(f"  🔒 Avatar HTTPS (mkcert) →  https://localhost:{port}/avatar.html")
    print(f"  Certificado de confianza — el micrófono funcionará sin problemas.")
    print("=" * 60)
    print()

    import app as avatar_app
    avatar_app.main()


# ─── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Servidor avatar con HTTPS via mkcert (desarrollo local)"
    )
    parser.add_argument("--port",  type=int, default=8010,        help="Puerto HTTP (default: 8010)")
    parser.add_argument("--cert",  default=DEFAULT_CERT,          help="Ruta al certificado PEM")
    parser.add_argument("--key",   default=DEFAULT_KEY,           help="Ruta a la clave PEM")
    args = parser.parse_args()

    check_certs(args.cert, args.key)
    patch_and_run(args.port, args.cert, args.key)
