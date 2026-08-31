###############################################################################
#  Kokoro TTS — TTS local de alta calidad, sin servidor externo
#  Modelo: hexgrad/Kokoro-82M | Idioma: español (lang_code='e')
#  Voz configurada via --REF_FILE (ej: ef_dora, em_alex, em_santa)
#
#  Instalación:
#    pip install "kokoro>=0.9.4"
#    + espeak-ng instalado en el sistema (para fonematización en español)
###############################################################################

import time
import numpy as np
import resampy

from utils.logger import logger
from .base_tts import BaseTTS, State
from registry import register


@register("tts", "kokoro")
class KokoroTTS(BaseTTS):
    """
    TTS local usando Kokoro-82M.
    Ventaja principal: elimina la latencia de red de EdgeTTS (~300-800ms)
    ya que todo corre localmente en CPU/GPU.

    Uso:
        python setup_ssl.py ... --tts kokoro --REF_FILE ef_dora
    """

    KOKORO_SAMPLE_RATE = 24000  # Kokoro siempre genera a 24kHz

    def __init__(self, opt, parent):
        super().__init__(opt, parent)

        # Voz: se toma de --REF_FILE. Si no se pasa, usa ef_dora por defecto.
        self.voice = getattr(opt, 'REF_FILE', 'ef_dora') or 'ef_dora'

        logger.info(f"[Kokoro TTS] Inicializando pipeline español (lang_code='e')...")
        t = time.time()
        try:
            from kokoro import KPipeline
            # lang_code='e' = español; el modelo se descarga automáticamente (~350MB)
            # la primera vez que se usa.
            self.pipeline = KPipeline(lang_code='e')
            logger.info(
                f"[Kokoro TTS] Listo en {time.time() - t:.2f}s | "
                f"Voz: {self.voice} | Sample rate out: {self.sample_rate}Hz"
            )
        except ImportError:
            logger.error(
                "[Kokoro TTS] No se encontró el paquete 'kokoro'. "
                "Instálalo con: pip install \"kokoro>=0.9.4\""
            )
            raise
        except Exception as e:
            logger.error(f"[Kokoro TTS] Error al inicializar el pipeline: {e}")
            raise

    def txt_to_audio(self, msg: tuple[str, dict]):
        """
        Genera audio a partir de texto usando Kokoro y lo envía al avatar
        en chunks de 20ms para que empiece a hablar lo antes posible
        (streaming progresivo).
        """
        text, textevent = msg

        voice = textevent.get('tts', {}).get('ref_file', self.voice)

        logger.info(f"[Kokoro TTS] Sintetizando ({len(text)} chars): \"{text[:60]}{'…' if len(text) > 60 else ''}\"")
        t = time.time()

        try:
            # Kokoro devuelve un generador: (graphemes, phonemes, audio_np_float32)
            # El audio ya viene en float32 a 24kHz, listo para resampling.
            generator = self.pipeline(text, voice=voice)

            leftover = np.array([], dtype=np.float32)
            first_chunk_sent = False
            segment_idx = 0

            for _gs, _ps, audio_segment in generator:
                if self.state != State.RUNNING:
                    break

                if audio_segment is None or len(audio_segment) == 0:
                    continue

                segment_idx += 1
                logger.info(
                    f"[Kokoro TTS] Segmento {segment_idx} generado en "
                    f"{time.time() - t:.3f}s ({len(audio_segment)} samples @ 24kHz)"
                )

                # Convertir a numpy float32 si es un Tensor de PyTorch
                if hasattr(audio_segment, 'detach'):
                    audio_np = audio_segment.detach().cpu().numpy().astype(np.float32)
                else:
                    audio_np = np.asarray(audio_segment, dtype=np.float32)
                
                if audio_np.ndim > 1:
                    audio_np = audio_np.squeeze()

                # Resamplear de 24kHz → 16kHz (sample_rate del sistema)
                audio_16k = resampy.resample(
                    audio_np,
                    sr_orig=self.KOKORO_SAMPLE_RATE,
                    sr_new=self.sample_rate
                )

                # Concatenar con el sobrante del segmento anterior
                stream = np.concatenate((leftover, audio_16k))

                idx = 0
                streamlen = stream.shape[0]

                while streamlen >= self.chunk and self.state == State.RUNNING:
                    eventpoint = {}

                    if not first_chunk_sent:
                        # Primer chunk: señalizar inicio de habla al avatar
                        eventpoint = {'status': 'start', 'text': text}
                        first_chunk_sent = True
                        logger.info(
                            f"[Kokoro TTS] Primer chunk enviado al avatar "
                            f"en {time.time() - t:.3f}s"
                        )

                    eventpoint.update(**textevent)
                    self.parent.put_audio_frame(stream[idx:idx + self.chunk], eventpoint)
                    idx += self.chunk
                    streamlen -= self.chunk

                # Guardar sobrante para el próximo segmento
                leftover = stream[idx:]

            # Señalizar fin de habla (aunque no queden chunks completos)
            if self.state == State.RUNNING:
                eventpoint = {'status': 'end', 'text': text}
                eventpoint.update(**textevent)
                self.parent.put_audio_frame(np.zeros(self.chunk, dtype=np.float32), eventpoint)

            logger.info(f"[Kokoro TTS] Síntesis completada en {time.time() - t:.3f}s total")

        except Exception as e:
            logger.exception(f"[Kokoro TTS] Error en txt_to_audio: {e}")
