###############################################################################
#  Kokoro TTS — TTS local de alta calidad, sin servidor externo
#  Modelo: hexgrad/Kokoro-82M | Idioma: español (lang_code='e')
#  Voz masculina por defecto: em_alex (configurable via --REF_FILE)
#
#  Instalación:
#    pip install "kokoro>=0.9.4"
#    + espeak-ng instalado en el sistema (para fonematización en español)
###############################################################################

import time
import re
import torch
import numpy as np
import resampy

from utils.logger import logger
from .base_tts import BaseTTS, State
from registry import register


def normalize_text_for_tts(text: str) -> str:
    """
    Normaliza y limpia el texto para síntesis de voz en Kokoro:
    - Remueve puntos en separadores de miles (ej: '1.990' -> '1990', '45.990' -> '45990',
      '599.990' -> '599990', '1.069.990' -> '1069990') para que no haga pausas.
    - Remueve caracteres especiales que lee el TTS: asteriscos (*), flechas (→),
      guiones (- o —), viñetas (•), corchetes ([ ]), barras (| o /), almohadillas (#), etc.
    - Convierte el símbolo '%' a la palabra 'por ciento'.
    - Elimina emojis y caracteres no pronunciables.
    """
    if not text:
        return text

    # 1. Porcentajes
    text = re.sub(r'(\d+)\s*%', r'\1 por ciento', text)

    # 2. Convertir precios con signo $ a pesos (ej: $599.990 -> 599.990 pesos)
    text = re.sub(r'\$(\d[\d\.]*)\s*(?:pesos)?', r'\1 pesos', text)

    # 3. Flechas
    text = re.sub(r'[→⇒➜➞➝➔]|->|=>|<-|<=|↔', ' ', text)

    # 4. Eliminar markdown de negrita, cursiva, encabezados
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`+([^`]+)`+', r'\1', text)
    text = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.MULTILINE)

    # 5. Eliminar viñetas, bullets, guiones y paréntesis en cualquier posición
    text = re.sub(r'[-—–]+', ' ', text)
    text = re.sub(r'[*#|_\\/\[\]{}~^<>•·●○■◆▪\(\)]', ' ', text)

    # 6. Eliminar emojis
    text = re.sub(
        r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]',
        '',
        text
    )

    # 7. Eliminar puntos de miles en números (soporta múltiples agrupaciones de 3 dígitos)
    while re.search(r'(\d+)\.(\d{3})(?!\d)', text):
        text = re.sub(r'(\d+)\.(\d{3})(?!\d)', r'\1\2', text)

    # 8. Limpiar espacios y signos redundantes
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    text = re.sub(r'[,]{2,}', ',', text)
    text = re.sub(r'[.]{2,}', '.', text)
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()


@register("tts", "kokoro")
class KokoroTTS(BaseTTS):
    """
    TTS local usando Kokoro-82M con voz masculina en español.
    Ventaja principal: elimina la latencia de red de EdgeTTS (~300-800ms)
    ya que todo corre localmente en GPU/CPU.

    Uso:
        python setup_ssl.py ... --tts kokoro --REF_FILE em_alex
    """

    KOKORO_SAMPLE_RATE = 24000  # Kokoro siempre genera a 24kHz

    def __init__(self, opt, parent):
        super().__init__(opt, parent)

        # Voz masculina por defecto para demo Paris: em_alex.
        # Si se pasa --REF_FILE diferente (ej: em_santa, ef_dora), se respeta.
        self.voice = getattr(opt, 'REF_FILE', 'em_alex') or 'em_alex'

        # Velocidad de habla (por defecto 1.10 = 10% más rápido para cadencia más viva y fluida)
        self.speed = float(getattr(opt, 'tts_speed', 1.10))

        # Determinar dispositivo de inferencia (GPU CUDA preferido)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        logger.info(f"[Kokoro TTS] Inicializando pipeline español (lang_code='e') en device={self.device} con voz '{self.voice}' (speed={self.speed})...")
        t = time.time()
        try:
            from kokoro import KPipeline
            # lang_code='e' = español; se especifica device ('cuda' o 'cpu') para máxima velocidad
            self.pipeline = KPipeline(lang_code='e', device=self.device)
            # Warmup inicial en GPU/CPU para que la primera consulta sea instantánea
            try:
                logger.info("[Kokoro TTS] Ejecutando warmup inicial...")
                _ = list(self.pipeline("Hola", voice=self.voice, speed=self.speed))
                logger.info("[Kokoro TTS] Warmup completado con éxito.")
            except Exception as e:
                logger.warning(f"[Kokoro TTS] Error en warmup inicial: {e}")

            logger.info(
                f"[Kokoro TTS] Listo en {time.time() - t:.2f}s | "
                f"Voz: {self.voice} | Device: {self.device} | Speed: {self.speed} | Sample rate out: {self.sample_rate}Hz"
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

        logger.info(f"[Kokoro TTS] Sintetizando ({len(text)} chars, speed={self.speed}): \"{text[:60]}{'…' if len(text) > 60 else ''}\"")
        t = time.time()

        try:
            # Normalizar números para pronunciación correcta en español (ej: 599.990 -> 599990)
            clean_text = normalize_text_for_tts(text)

            # Kokoro devuelve un generador: (graphemes, phonemes, audio_np_float32)
            # El audio ya viene en float32 a 24kHz, listo para resampling.
            generator = self.pipeline(clean_text, voice=voice, speed=self.speed)

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

                if not first_chunk_sent:
                    # Fix jitter buffer: inyectar silencio preparatorio INMEDIATAMENTE
                    # antes del primer audio real ya computado. Al ser parte del mismo stream,
                    # el navegador recibe paquetes continuos y el buffer de audio arranca sin
                    # que se pierdan las primeras palabras mientras la GPU calculaba el audio.
                    JITTER_PREFILL_CHUNKS = 12  # 12 × 20ms = 240ms de prefill continuo
                    silence = np.zeros(self.chunk * JITTER_PREFILL_CHUNKS, dtype=np.float32)
                    stream = np.concatenate((silence, stream))

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
