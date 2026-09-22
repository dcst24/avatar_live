#!/usr/bin/env python3
"""
Script de pre-generación de caché TTS.

Genera un archivo .npy (float32, 16kHz) por cada frase en cache_phrases.txt
usando el pipeline de Kokoro, y los guarda en tts/cache/.

Los archivos se nombran con el MD5 del texto normalizado + voz, para que
KokoroTTS los encuentre automáticamente en tiempo real.

Uso:
    python tts/generate_cache.py --voice ef_dora
    python tts/generate_cache.py --voice ef_dora --phrases_file tts/cache_phrases.txt
    python tts/generate_cache.py --voice ef_dora --speed 1.10

Para regenerar un audio específico (sobrescribir), simplemente volver a ejecutar.
"""

import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np

# ── Asegurar que el root del proyecto esté en el path ──────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tts.kokoro_tts import normalize_text_for_tts
from utils.audio import resample_audio
from utils.logger import logger

KOKORO_SAMPLE_RATE = 24000
TARGET_SAMPLE_RATE = 16000
CACHE_DIR = Path(__file__).parent / "cache"


def phrase_to_cache_key(text: str, voice: str) -> str:
    """
    Genera la clave MD5 usada para nombrar el .npy en el disco.
    Debe ser idéntica a la que usa KokoroTTS._get_cache_key() en tiempo real.
    """
    normalized = normalize_text_for_tts(text).strip().lower()
    return hashlib.md5(f"{normalized}|{voice}".encode()).hexdigest()


def generate_phrase(pipeline, phrase: str, voice: str, speed: float) -> np.ndarray:
    """
    Genera audio para una frase y devuelve un array float32 continuo a 16kHz.
    Aplica la misma normalización y resampling que KokoroTTS.txt_to_audio().
    """
    clean_text = normalize_text_for_tts(phrase)
    generator = pipeline(clean_text, voice=voice, speed=speed)

    segments_16k = []
    for _gs, _ps, audio_segment in generator:
        if audio_segment is None or len(audio_segment) == 0:
            continue

        if hasattr(audio_segment, 'detach'):
            audio_np = audio_segment.detach().cpu().numpy().astype(np.float32)
        else:
            audio_np = np.asarray(audio_segment, dtype=np.float32)

        if audio_np.ndim > 1:
            audio_np = audio_np.squeeze()

        # Resamplear de 24kHz → 16kHz (igual que txt_to_audio)
        audio_16k = resample_audio(audio_np, from_rate=KOKORO_SAMPLE_RATE, to_rate=TARGET_SAMPLE_RATE)
        segments_16k.append(audio_16k)

    if not segments_16k:
        return np.array([], dtype=np.float32)

    return np.concatenate(segments_16k).astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description="Pre-genera audios TTS en caché")
    parser.add_argument("--voice", default="ef_dora", help="Voz Kokoro a usar (ej: ef_dora, em_alex)")
    parser.add_argument("--speed", type=float, default=1.10, help="Velocidad de síntesis (default: 1.10)")
    parser.add_argument(
        "--phrases_file",
        default=str(Path(__file__).parent / "cache_phrases.txt"),
        help="Archivo de texto con las frases a cachear (una por línea)"
    )
    parser.add_argument("--force", action="store_true", help="Regenerar aunque ya exista el .npy")
    args = parser.parse_args()

    # ── Cargar frases ───────────────────────────────────────────────────────────
    phrases_file = Path(args.phrases_file)
    if not phrases_file.exists():
        logger.error(f"[Cache] No se encontró el archivo de frases: {phrases_file}")
        sys.exit(1)

    phrases = [
        line.strip()
        for line in phrases_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not phrases:
        logger.error("[Cache] El archivo de frases está vacío.")
        sys.exit(1)

    logger.info(f"[Cache] {len(phrases)} frases encontradas | voz={args.voice} | speed={args.speed}")

    # ── Crear directorio de caché ───────────────────────────────────────────────
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Inicializar pipeline de Kokoro ──────────────────────────────────────────
    import torch
    from kokoro import KPipeline

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"[Cache] Inicializando Kokoro en device={device}...")
    pipeline = KPipeline(lang_code='e', device=device)

    # Warmup
    logger.info("[Cache] Warmup...")
    _ = list(pipeline("Hola", voice=args.voice, speed=args.speed))
    logger.info("[Cache] Warmup OK")

    # ── Generar cada frase ──────────────────────────────────────────────────────
    total = len(phrases)
    generated = 0
    skipped = 0

    for i, phrase in enumerate(phrases, 1):
        key = phrase_to_cache_key(phrase, args.voice)
        out_path = CACHE_DIR / f"{key}.npy"

        if out_path.exists() and not args.force:
            logger.info(f"[Cache] [{i}/{total}] Ya existe, saltando: '{phrase[:60]}'")
            skipped += 1
            continue

        logger.info(f"[Cache] [{i}/{total}] Generando: '{phrase[:70]}'")
        t0 = time.time()

        try:
            audio = generate_phrase(pipeline, phrase, args.voice, args.speed)
            if len(audio) == 0:
                logger.warning(f"[Cache] [{i}/{total}] Audio vacío para: '{phrase}'")
                continue

            np.save(str(out_path), audio)
            duration_audio = len(audio) / TARGET_SAMPLE_RATE
            logger.info(
                f"[Cache] [{i}/{total}] OK — {duration_audio:.2f}s de audio, "
                f"generado en {time.time() - t0:.2f}s → {out_path.name}"
            )
            generated += 1

        except Exception as e:
            logger.error(f"[Cache] [{i}/{total}] ERROR generando '{phrase}': {e}")

    # ── Resumen ─────────────────────────────────────────────────────────────────
    logger.info(f"\n[Cache] ─────────────────────────────────────────")
    logger.info(f"[Cache] Completado: {generated} generados, {skipped} saltados, {total - generated - skipped} errores")
    logger.info(f"[Cache] Directorio: {CACHE_DIR}")
    logger.info(f"[Cache] ─────────────────────────────────────────")


if __name__ == "__main__":
    main()
