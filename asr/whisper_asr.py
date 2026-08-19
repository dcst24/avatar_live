###############################################################################
#  WhisperASR — Transcripción local con soporte doble backend:
#
#  Backend 1: openai-whisper  (usa PyTorch — CUDA funciona en Jetson con JetPack)
#  Backend 2: faster-whisper  (usa CTranslate2 — CUDA solo en x86, más rápido)
#
#  Se intenta primero faster-whisper. Si CTranslate2 no soporta CUDA en la
#  plataforma actual, se usa openai-whisper automáticamente.
#
#  Flujo de audio:
#    - Recibe chunks PCM 16-bit LE, 16kHz, mono
#    - VAD simple por energía RMS para detectar segmentos de habla
#    - Al detectar fin de habla → transcribe el segmento acumulado
#    - Llama on_transcript(text, is_final)
###############################################################################

import numpy as np
import threading
import time
from typing import Optional, Callable
from utils.logger import logger


# ─── Constantes de VAD ────────────────────────────────────────────────────────
SAMPLE_RATE      = 16000    # Hz — debe coincidir con lo que envía el navegador
SILENCE_THRESH   = 0.008    # RMS por debajo del cual se considera silencio
SILENCE_FRAMES   = 18       # frames de silencio consecutivos para cortar (~1.1s a 60ms/frame)
MIN_SPEECH_SECS  = 0.3      # segundos mínimos de habla antes de transcribir
MAX_BUFFER_SECS  = 25       # segundos máximos antes de forzar transcripción
CHUNK_SAMPLES    = 960      # muestras por chunk (60ms a 16kHz)


class WhisperASR:
    """
    Transcriptor de audio en tiempo real.

    Detecta automáticamente el mejor backend disponible:
      - faster-whisper + CTranslate2 CUDA  → x86 con GPU NVIDIA
      - openai-whisper + PyTorch CUDA       → Jetson Orin NX (JetPack)
      - openai-whisper + PyTorch CPU        → Cualquier plataforma (más lento)

    Uso:
        asr = WhisperASR(model_size='small', language='es', device='auto')
        asr.load_model()
        asr.start()
        asr.feed(pcm_bytes)   # llamar con cada chunk de audio
        asr.stop()
    """

    def __init__(
        self,
        model_size: str = 'small',
        language: str = 'es',
        device: str = 'auto',
        on_transcript: Optional[Callable[[str, bool], None]] = None,
    ):
        self.model_size   = model_size
        self.language     = language
        self.on_transcript = on_transcript
        self._backend     = None   # 'faster-whisper' | 'openai-whisper'
        self._model       = None
        self._device      = self._resolve_device(device)

        # ── Buffer y estado VAD ──────────────────────────────────────────────
        self._lock           = threading.Lock()
        self._audio_buffer   = np.array([], dtype=np.float32)
        self._silence_count  = 0
        self._speech_started = False
        self._speech_samples = 0
        self._running        = False

        logger.info(
            f"[WhisperASR] Config: model={model_size}, lang={language}, device={self._device}"
        )

    # ── Resolución de device ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != 'auto':
            return device
        try:
            import torch
            return 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            return 'cpu'

    # ── Carga del modelo ──────────────────────────────────────────────────────

    def load_model(self):
        """
        Carga el modelo Whisper. Detecta automáticamente el mejor backend.
        Prioridad: faster-whisper con CUDA → faster-whisper con CPU → openai-whisper
        """
        if self._model is not None:
            return

        # ── Intento 1: faster-whisper ─────────────────────────────────────────
        try:
            from faster_whisper import WhisperModel
            compute_type = 'int8_float16' if self._device == 'cuda' else 'int8'
            logger.info(
                f"[WhisperASR] Cargando con faster-whisper: model={self.model_size}, "
                f"device={self._device}, compute={compute_type}"
            )
            self._model = WhisperModel(
                self.model_size,
                device=self._device,
                compute_type=compute_type,
            )
            self._backend = 'faster-whisper'
            logger.info(f"[WhisperASR] Backend: faster-whisper ({self._device})")
            return
        except Exception as e:
            logger.warning(f"[WhisperASR] faster-whisper no disponible ({e}), probando openai-whisper...")

        # ── Intento 2: openai-whisper (PyTorch — CUDA en Jetson) ─────────────
        try:
            import whisper as oai_whisper
            logger.info(
                f"[WhisperASR] Cargando con openai-whisper: model={self.model_size}, "
                f"device={self._device}"
            )
            self._model = oai_whisper.load_model(self.model_size, device=self._device)
            self._backend = 'openai-whisper'
            logger.info(f"[WhisperASR] Backend: openai-whisper (PyTorch, device={self._device})")
            return
        except Exception as e:
            logger.error(f"[WhisperASR] openai-whisper también falló: {e}")
            raise RuntimeError(
                f"No se pudo cargar ningún backend de Whisper. "
                f"Instala: pip install openai-whisper\n"
                f"Último error: {e}"
            )

    # ── API pública ───────────────────────────────────────────────────────────

    def start(self):
        """Inicia una sesión de escucha. Llamar al inicio de cada conversación."""
        with self._lock:
            self._audio_buffer   = np.array([], dtype=np.float32)
            self._silence_count  = 0
            self._speech_started = False
            self._speech_samples = 0
            self._running        = True
        logger.debug("[WhisperASR] Sesión iniciada.")

    def stop(self) -> Optional[str]:
        """
        Detiene la sesión y fuerza la transcripción del buffer acumulado.
        Retorna el texto transcrito o None.
        """
        with self._lock:
            self._running = False
            buffer = self._audio_buffer.copy()
            self._audio_buffer = np.array([], dtype=np.float32)

        if len(buffer) >= int(MIN_SPEECH_SECS * SAMPLE_RATE):
            text = self._transcribe(buffer)
            if text and self.on_transcript:
                self.on_transcript(text, True)
            return text
        return None

    def reset(self):
        """Resetea el buffer sin transcribir (p.ej. cuando el avatar empieza a hablar)."""
        with self._lock:
            self._audio_buffer   = np.array([], dtype=np.float32)
            self._silence_count  = 0
            self._speech_started = False
            self._speech_samples = 0
        logger.debug("[WhisperASR] Buffer reseteado.")

    def feed(self, pcm_bytes: bytes) -> Optional[str]:
        """
        Alimenta el ASR con un chunk de audio PCM 16-bit LE, 16kHz, mono.
        Cuando detecta fin de habla por VAD, transcribe y llama on_transcript.

        Returns:
            Texto transcrito si hubo resultado, None si aún acumulando.
        """
        if not self._running or self._model is None:
            return None

        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception as e:
            logger.warning(f"[WhisperASR] Error decodificando PCM: {e}")
            return None

        rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) > 0 else 0.0
        is_speech = rms > SILENCE_THRESH

        with self._lock:
            if not self._running:
                return None

            if is_speech:
                self._silence_count  = 0
                self._speech_started = True
                self._speech_samples += len(samples)
                self._audio_buffer   = np.concatenate([self._audio_buffer, samples])
            else:
                if self._speech_started:
                    self._silence_count += 1
                    self._audio_buffer = np.concatenate([self._audio_buffer, samples])

            should_transcribe = (
                self._speech_started and
                self._speech_samples >= int(MIN_SPEECH_SECS * SAMPLE_RATE) and
                self._silence_count >= SILENCE_FRAMES
            )
            if self._speech_started and len(self._audio_buffer) >= int(MAX_BUFFER_SECS * SAMPLE_RATE):
                should_transcribe = True

            if not should_transcribe:
                return None

            buffer = self._audio_buffer.copy()
            self._audio_buffer   = np.array([], dtype=np.float32)
            self._silence_count  = 0
            self._speech_started = False
            self._speech_samples = 0

        text = self._transcribe(buffer)
        if text and self.on_transcript:
            self.on_transcript(text, True)
        return text

    # ── Transcripción interna ─────────────────────────────────────────────────

    def _transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe un array float32 (16kHz, mono) con el backend activo."""
        if self._model is None or len(audio) == 0:
            return None
        try:
            t0 = time.perf_counter()

            if self._backend == 'faster-whisper':
                text = self._transcribe_faster(audio)
            else:
                text = self._transcribe_openai(audio)

            elapsed = time.perf_counter() - t0
            if text:
                logger.info(f"[WhisperASR][{self._backend}] ({elapsed:.2f}s): \"{text}\"")
            else:
                logger.debug(f"[WhisperASR] Sin habla detectada ({elapsed:.2f}s)")
            return text or None
        except Exception as e:
            logger.error(f"[WhisperASR] Error en transcripción: {e}")
            return None

    def _transcribe_faster(self, audio: np.ndarray) -> Optional[str]:
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=100),
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            temperature=0.0,
        )
        return " ".join(seg.text.strip() for seg in segments).strip() or None

    def _transcribe_openai(self, audio: np.ndarray) -> Optional[str]:
        result = self._model.transcribe(
            audio,
            language=self.language,
            fp16=(self._device == 'cuda'),
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            temperature=0.0,
            best_of=1,
            beam_size=3,
        )
        return result.get('text', '').strip() or None
