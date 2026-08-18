###############################################################################
#  WhisperASR — Transcripción local con faster-whisper
#  Recibe chunks de audio PCM 16-bit LE, 16kHz, mono.
#  Acumula muestras, aplica VAD simple por energía y transcribe en segmentos.
###############################################################################

import numpy as np
import threading
import time
from typing import Optional, Callable
from utils.logger import logger


# ─── Constantes de VAD ────────────────────────────────────────────────────────
SAMPLE_RATE      = 16000          # Hz — debe coincidir con lo que envía el navegador
SILENCE_THRESH   = 0.008          # RMS por debajo del cual se considera silencio
SILENCE_FRAMES   = 25             # frames de silencio consecutivos para cortar (~1.5s con chunks de 60ms)
MIN_SPEECH_SECS  = 0.3            # segundos mínimos de habla antes de transcribir
MAX_BUFFER_SECS  = 30             # segundos máximos de buffer antes de forzar transcripción
CHUNK_SAMPLES    = 960            # muestras por chunk (60ms a 16kHz)


class WhisperASR:
    """
    Transcriptor de audio en tiempo real basado en faster-whisper.

    Uso:
        asr = WhisperASR(model_size='small', language='es', device='cpu')
        asr.start()

        # En cada chunk de audio recibido del cliente:
        asr.feed(pcm_bytes)

        # Para detener y vaciar el buffer:
        asr.stop()

    Los resultados llegan por el callback `on_transcript(text, is_final)`.
    """

    def __init__(
        self,
        model_size: str = 'small',
        language: str = 'es',
        device: str = 'auto',
        compute_type: str = 'auto',
        on_transcript: Optional[Callable[[str, bool], None]] = None,
    ):
        """
        Args:
            model_size:    Tamaño del modelo Whisper ('tiny','base','small','medium','large-v3')
            language:      Código de idioma para faster-whisper (p.ej. 'es')
            device:        'cuda', 'cpu' o 'auto' (detecta CUDA automáticamente)
            compute_type:  'float16', 'int8', 'auto' (auto elige el mejor según device)
            on_transcript: Callback(text: str, is_final: bool) llamado con cada resultado
        """
        self.model_size   = model_size
        self.language     = language
        self.on_transcript = on_transcript

        # ── Resolver device y compute_type ──────────────────────────────────
        if device == 'auto':
            try:
                import torch
                self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
            except ImportError:
                self._device = 'cpu'
        else:
            self._device = device

        if compute_type == 'auto':
            self._compute_type = 'float16' if self._device == 'cuda' else 'int8'
        else:
            self._compute_type = compute_type

        # ── Buffer de audio y estado VAD ─────────────────────────────────────
        self._lock           = threading.Lock()
        self._audio_buffer   = np.array([], dtype=np.float32)
        self._silence_count  = 0
        self._speech_started = False
        self._speech_samples = 0
        self._running        = False
        self._model          = None

        logger.info(
            f"[WhisperASR] Config: model={model_size}, lang={language}, "
            f"device={self._device}, compute={self._compute_type}"
        )

    # ── Carga del modelo ──────────────────────────────────────────────────────

    def load_model(self):
        """Carga el modelo faster-whisper. Llamar una sola vez al iniciar el servidor."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            logger.info(f"[WhisperASR] Cargando modelo '{self.model_size}' en {self._device}...")
            self._model = WhisperModel(
                self.model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("[WhisperASR] Modelo cargado correctamente.")
        except Exception as e:
            logger.error(f"[WhisperASR] Error cargando modelo: {e}")
            raise

    # ── API pública ───────────────────────────────────────────────────────────

    def start(self):
        """Activa el receptor de audio. Debe llamarse al iniciar cada sesión de escucha."""
        with self._lock:
            self._audio_buffer   = np.array([], dtype=np.float32)
            self._silence_count  = 0
            self._speech_started = False
            self._speech_samples = 0
            self._running        = True
        logger.debug("[WhisperASR] Sesión de escucha iniciada.")

    def stop(self):
        """
        Detiene la sesión de escucha y fuerza la transcripción del buffer acumulado.
        Retorna el texto transcrito o None si el buffer estaba vacío.
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
        Si detecta fin de habla por VAD, transcribe y llama on_transcript.

        Returns:
            Texto transcrito si hubo resultado, None si aún acumulando.
        """
        if not self._running or self._model is None:
            return None

        # Convertir bytes PCM 16-bit a float32 normalizado [-1, 1]
        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception as e:
            logger.warning(f"[WhisperASR] Error decodificando PCM: {e}")
            return None

        # ── VAD simple por energía RMS ────────────────────────────────────────
        rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) > 0 else 0.0

        with self._lock:
            if not self._running:
                return None

            is_speech = rms > SILENCE_THRESH

            if is_speech:
                self._silence_count  = 0
                self._speech_started = True
                self._speech_samples += len(samples)
                self._audio_buffer   = np.concatenate([self._audio_buffer, samples])
            else:
                if self._speech_started:
                    self._silence_count += 1
                    # Agregar silencio al buffer (para contexto)
                    self._audio_buffer = np.concatenate([self._audio_buffer, samples])

            # ── Condición de corte: silencio suficiente después de habla ──────
            should_transcribe = (
                self._speech_started and
                self._speech_samples >= int(MIN_SPEECH_SECS * SAMPLE_RATE) and
                self._silence_count >= SILENCE_FRAMES
            )

            # ── Condición de corte: buffer demasiado largo ────────────────────
            if self._speech_started and len(self._audio_buffer) >= int(MAX_BUFFER_SECS * SAMPLE_RATE):
                should_transcribe = True

            if not should_transcribe:
                return None

            # Tomar buffer y resetear estado
            buffer = self._audio_buffer.copy()
            self._audio_buffer   = np.array([], dtype=np.float32)
            self._silence_count  = 0
            self._speech_started = False
            self._speech_samples = 0

        # Transcribir fuera del lock (puede ser lento)
        text = self._transcribe(buffer)
        if text and self.on_transcript:
            self.on_transcript(text, True)
        return text

    # ── Transcripción interna ─────────────────────────────────────────────────

    def _transcribe(self, audio: np.ndarray) -> Optional[str]:
        """
        Transcribe un array float32 de audio con faster-whisper.
        Retorna el texto transcrito o None si no se detectó habla.
        """
        if self._model is None or len(audio) == 0:
            return None
        try:
            t0 = time.perf_counter()
            segments, info = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=5,
                vad_filter=True,          # VAD interno de Whisper como segunda capa
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                temperature=0.0,          # Determinístico
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            elapsed = time.perf_counter() - t0
            if text:
                logger.info(f"[WhisperASR] Transcripción ({elapsed:.2f}s): \"{text}\"")
            else:
                logger.debug(f"[WhisperASR] Sin habla detectada ({elapsed:.2f}s)")
            return text or None
        except Exception as e:
            logger.error(f"[WhisperASR] Error en transcripción: {e}")
            return None
