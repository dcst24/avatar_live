import logging
import sys

# Configuración de logger robusto compatible con Windows (CP1252 / UTF-8)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# FileHandler con codificación explícita UTF-8 y reemplazo de caracteres no mapeables
fhandler = logging.FileHandler('livetalking.log', encoding='utf-8', errors='replace')
fhandler.setFormatter(formatter)
fhandler.setLevel(logging.INFO)
logger.addHandler(fhandler)

# StreamHandler seguro para terminal / consola
try:
    chandler = logging.StreamHandler(sys.stdout)
    chandler.setLevel(logging.INFO)
    chandler.setFormatter(formatter)
    logger.addHandler(chandler)
except Exception:
    pass