import os
import hashlib
import time
import asyncio
import numpy as np
import soundfile as sf
import edge_tts
from io import BytesIO

from utils.logger import logger
from utils.audio import resample_audio
from .base_tts import BaseTTS, State
from registry import register

CACHE_DIR = "./data/cache_tts"
os.makedirs(CACHE_DIR, exist_ok=True)

@register("tts", "edgetts")
class EdgeTTS(BaseTTS):
    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        voicename = textevent.get('tts', {}).get('ref_file', self.opt.REF_FILE)

        # Generar clave única para cache local en disco
        cache_key = hashlib.md5(f"{voicename}:{text}".encode('utf-8')).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.wav")

        t = time.time()
        stream = None

        if os.path.exists(cache_path):
            try:
                stream, sample_rate = sf.read(cache_path, dtype='float32')
                logger.info(f'[EdgeTTS CACHE HIT] audio cargado en {time.time()-t:.4f}s desde cache: "{text[:40]}"')
                if stream.ndim > 1:
                    stream = stream[:, 0]
                if sample_rate != self.sample_rate:
                    stream = resample_audio(stream, sample_rate, self.sample_rate)
            except Exception as e:
                logger.warning(f'[EdgeTTS CACHE ERR] {e}')
                stream = None

        if stream is None:
            # Descarga desde Microsoft Edge TTS
            asyncio.new_event_loop().run_until_complete(self.__main(voicename, text))
            logger.info(f'-------edge tts cloud time: {time.time()-t:.4f}s')
            if self.input_stream.getbuffer().nbytes <= 0:
                logger.error('edgetts err!!!!!')
                return

            self.input_stream.seek(0)
            stream = self.__create_bytes_stream(self.input_stream)
            self.input_stream.seek(0)
            self.input_stream.truncate()

            # Guardar en cache para ejecuciones futuras (0ms de latencia)
            try:
                sf.write(cache_path, stream, self.sample_rate)
            except Exception as e:
                logger.warning(f'No se pudo guardar audio en cache: {e}')

        streamlen = stream.shape[0]
        idx = 0
        while streamlen >= self.chunk and self.state == State.RUNNING:
            eventpoint = {}
            streamlen -= self.chunk
            if idx == 0:
                eventpoint = {'status': 'start', 'text': text}
            elif streamlen < self.chunk:
                eventpoint = {'status': 'end', 'text': text}
            eventpoint.update(**textevent)
            self.parent.put_audio_frame(stream[idx:idx+self.chunk], eventpoint)
            idx += self.chunk

    def __create_bytes_stream(self, byte_stream):
        stream, sample_rate = sf.read(byte_stream)
        logger.info(f'[INFO] tts audio stream {sample_rate}: {stream.shape}')
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.info(f'[WARN] audio has {stream.shape[1]} channels, only use the first.')
            stream = stream[:, 0]

        if sample_rate != self.sample_rate and stream.shape[0] > 0:
            logger.info(f'[WARN] audio sample rate is {sample_rate}, resampling into {self.sample_rate}.')
            stream = resample_audio(stream, sample_rate, self.sample_rate)

        return stream

    async def __main(self, voicename: str, text: str):
        try:
            # +15% de velocidad para mayor fluidez y menor tiempo de respuesta
            communicate = edge_tts.Communicate(text, voicename, rate="+15%")

            first = True
            async for chunk in communicate.stream():
                if first:
                    first = False
                if chunk["type"] == "audio" and self.state == State.RUNNING:
                    self.input_stream.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    pass
        except Exception as e:
            logger.exception('edgetts')

