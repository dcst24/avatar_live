"""
setup_ssl.py  –  Arranca el servidor con HTTPS usando certificado de CA local
                 (confiable por cualquier PC de la red, micrófono funciona sin advertencias)

Prerequisitos:
    Generar certificados con:  python gen_ssl_certs.py
    Instalar la CA en cada cliente:  .\install_ca.ps1  (PowerShell como Administrador)

Uso:
    python setup_ssl.py [--port 8010] [--cert ssl/server.pem] [--key ssl/server-key.pem]
                        [-- argumentos de app.py ...]

Ejemplo (equivalente a: python app.py --transport webrtc --model wav2lip --avatar_id easy_latina3):
    python setup_ssl.py --transport webrtc --model wav2lip --avatar_id easy_latina3

Accede desde CUALQUIER PC de la red:
    https://<IP_SERVIDOR>:<port>/avatar.html

Si agregas una nueva IP de red, regenera el certificado:
    python gen_ssl_certs.py          # reutiliza la CA existente
"""

import argparse
import os
import sys
import ssl

# Rutas de los certificados generados por gen_ssl_certs.py
DEFAULT_CERT = os.path.join(os.path.dirname(__file__), "ssl", "server.pem")
DEFAULT_KEY  = os.path.join(os.path.dirname(__file__), "ssl", "server-key.pem")


def check_certs(cert_path: str, key_path: str):
    """Verifica que los certificados existen, si no da instrucciones."""
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("[!] No se encontraron los certificados SSL.")
        print("    Genera los certificados ejecutando:")
        print()
        print("       python gen_ssl_certs.py")
        print()
        print("    Luego instala la CA en cada PC cliente:")
        print("       PowerShell (Administrador) > .\\install_ca.ps1")
        print()
        sys.exit(1)
    print(f"[OK] Certificado : {cert_path}")
    print(f"[OK] Clave privada: {key_path}")


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

    import socket
    try:
        hostname = socket.gethostname()
        ips = [info[4][0] for info in socket.getaddrinfo(hostname, None)
               if info[0] == socket.AF_INET and not info[4][0].startswith('127.')]
        ips = sorted(set(ips))
    except Exception:
        ips = []

    print()
    print("=" * 60)
    print(f"  HTTPS Avatar Server activo")
    print(f"  Microfono: OK (HTTPS con CA de confianza)")
    print()
    print(f"  Acceso local:")
    print(f"    https://localhost:{port}/avatar.html")
    if ips:
        print(f"  Acceso desde red local:")
        for ip in ips:
            print(f"    https://{ip}:{port}/avatar.html")
    print()
    print(f"  Si un cliente no confía en el cert, ejecutar en ese PC:")
    print(f"    PowerShell (Admin) > .\\install_ca.ps1")
    print("=" * 60)
    print()

    import app as avatar_app
    avatar_app.main()


# ─── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Servidor avatar con HTTPS (pasa cualquier arg de app.py directamente)",
        # No interrumpir en args desconocidos — se reenvían a app.py
        add_help=True,
    )
    parser.add_argument("--port",  type=int, default=8010,  help="Puerto HTTPS (default: 8010)")
    parser.add_argument("--cert",  default=DEFAULT_CERT,    help="Ruta al certificado PEM")
    parser.add_argument("--key",   default=DEFAULT_KEY,     help="Ruta a la clave PEM")

    # parse_known_args: captura --port/--cert/--key y deja el resto intacto
    args, app_args = parser.parse_known_args()

    # Si el usuario pasó --listenport en app_args, respetarlo; si no, inyectar el nuestro.
    if "--listenport" not in app_args:
        app_args += ["--listenport", str(args.port)]

    # Reemplazar sys.argv para que config.parse_args() (dentro de app.main()) lo lea
    sys.argv = [sys.argv[0]] + app_args

    check_certs(args.cert, args.key)
    patch_and_run(args.port, args.cert, args.key)
