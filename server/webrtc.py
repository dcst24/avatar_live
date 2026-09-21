###############################################################################
#  Copyright (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking
#  email: lipku@foxmail.com
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import asyncio
import json
import logging
import threading
import time
from typing import Tuple, Dict, Optional, Set, Union
import queue
from av.frame import Frame
from av.packet import Packet
from av import AudioFrame
import fractions
import numpy as np

AUDIO_PTIME = 0.020  # 20ms audio packetization
VIDEO_CLOCK_RATE = 90000
VIDEO_PTIME = 0.040 #1 / 25  # 30fps
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)
SAMPLE_RATE = 16000
AUDIO_TIME_BASE = fractions.Fraction(1, SAMPLE_RATE)

#from aiortc.contrib.media import MediaPlayer, MediaRelay
#from aiortc.rtcrtpsender import RTCRtpSender
from aiortc import (
    MediaStreamTrack,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
from utils.logger import logger as mylogger


class PlayerStreamTrack(MediaStreamTrack):
    """
    Pista de audio o video para WebRTC con temporización monotónica de alta precisión,
    prevención de desincronización de reloj y colas no bloqueantes.
    """

    def __init__(self, player, kind):
        super().__init__()
        self.kind = kind
        self._player = player
        self._queue = queue.Queue(maxsize=120)
        self._start_time: Optional[float] = None
        self._timestamp: int = 0
        self.last_frame = None

        if self.kind == 'video':
            self.frame_duration = VIDEO_PTIME      # 0.040s (25 fps)
            self.clock_rate = VIDEO_CLOCK_RATE     # 90000 Hz
            self.pts_step = int(VIDEO_PTIME * VIDEO_CLOCK_RATE) # 3600
            self.time_base = VIDEO_TIME_BASE
            self.framecount = 0
            self.lasttime = time.perf_counter()
            self.totaltime = 0
        else: # audio
            self.frame_duration = AUDIO_PTIME      # 0.020s
            self.clock_rate = SAMPLE_RATE          # 16000 Hz
            self.pts_step = int(AUDIO_PTIME * SAMPLE_RATE) # 320
            self.time_base = AUDIO_TIME_BASE

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        if self.readyState != "live":
            raise Exception("Track is no longer live")

        now = time.perf_counter()
        if self._start_time is None:
            if self._player and hasattr(self._player, "_shared_start_time") and self._player._shared_start_time:
                self._start_time = self._player._shared_start_time
            else:
                self._start_time = now
                if self._player:
                    self._player._shared_start_time = self._start_time
            self._timestamp = 0
            return self._timestamp, self.time_base

        self._timestamp += self.pts_step

        # Calcular tiempo esperado para este timestamp relativo al inicio
        expected_time = self._start_time + (self._timestamp / self.clock_rate)
        wait = expected_time - now

        if wait > 0.001:
            await asyncio.sleep(wait)
        elif wait < -0.15:
            # Si hay un retraso superior a 150ms (por carga o GC), resincronizar el reloj base
            # para evitar ráfagas descontroladas o timestamps desfasados con RTCP
            self._start_time = now - (self._timestamp / self.clock_rate)

        return self._timestamp, self.time_base

    async def recv(self) -> Union[Frame, Packet]:
        if self.readyState != "live":
            raise Exception("Track stopped")

        self._player._start(self)

        frame = None
        eventpoint = None

        # Esperar frame con timeout para no congelar el bucle de aiortc
        retry_count = 0
        while self.readyState == "live":
            try:
                frame, eventpoint = self._queue.get_nowait()
                break
            except queue.Empty:
                retry_count += 1
                if retry_count > 20: # ~100ms sin frame
                    # Si no hay frame en cola, reutilizar el último frame (video) o generar silencio (audio)
                    if self.kind == 'audio':
                        audio = np.zeros(int(SAMPLE_RATE * AUDIO_PTIME), dtype=np.int16)
                        frame = AudioFrame(format='s16', layout='mono', samples=audio.shape[0])
                        frame.planes[0].update(audio.tobytes())
                        frame.sample_rate = SAMPLE_RATE
                    elif self.last_frame is not None:
                        frame = self.last_frame
                    break
                await asyncio.sleep(0.005)

        if frame is None:
            if self.kind == 'audio':
                audio = np.zeros(int(SAMPLE_RATE * AUDIO_PTIME), dtype=np.int16)
                frame = AudioFrame(format='s16', layout='mono', samples=audio.shape[0])
                frame.planes[0].update(audio.tobytes())
                frame.sample_rate = SAMPLE_RATE
            else:
                self.stop()
                raise Exception("No frame available")

        self.last_frame = frame
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base

        if eventpoint and self._player is not None:
            self._player.notify(eventpoint)

        if self.kind == 'video':
            self.totaltime += (time.perf_counter() - self.lasttime)
            self.framecount += 1
            self.lasttime = time.perf_counter()
            if self.framecount == 100:
                mylogger.debug(f"WebRTC avg video fps: {self.framecount/self.totaltime:.2f}")
                self.framecount = 0
                self.totaltime = 0

        return frame

    def purge(self):
        """Purga todos los frames pendientes en cola para corte inmediato."""
        with self._queue.mutex:
            self._queue.queue.clear()

    def stop(self):
        super().stop()
        with self._queue.mutex:
            self._queue.queue.clear()
        if self._player is not None:
            self._player._stop(self)
            self._player = None

def player_worker_thread(
    quit_event,
    container
):
    try:
        container.render(quit_event)
    except Exception as e:
        mylogger.exception("Error en player_worker_thread:")

class HumanPlayer:

    def __init__(
        self, avatar_session, format=None, options=None, timeout=None, loop=False, decode=True
    ):
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None
        self._shared_start_time: Optional[float] = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__audio = PlayerStreamTrack(self, kind="audio")
        self.__video = PlayerStreamTrack(self, kind="video")

        self.__container = avatar_session
        if hasattr(self.__container, 'output'):
            self.__container.output._player = self

    def purge(self):
        """Purga buffers de audio WebRTC de forma instantánea.
        El video NO se purga para mantener flujo continuo y evitar pantalla negra."""
        if self.__audio:
            self.__audio.purge()

    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        # Inserción segura sin bloqueo de hilo: si la cola está llena, descartar el más viejo
        try:
            self.__video._queue.put_nowait((new_frame, None))
        except queue.Full:
            try:
                self.__video._queue.get_nowait()
            except queue.Empty:
                pass
            self.__video._queue.put_nowait((new_frame, None))

    def push_audio(self, frame, eventpoint=None):
        from av import AudioFrame
        new_frame = AudioFrame(format='s16', layout='mono', samples=frame.shape[0])
        new_frame.planes[0].update(frame.tobytes())
        new_frame.sample_rate = 16000
        # Inserción segura sin bloqueo de hilo: si la cola está llena, descartar el más viejo
        try:
            self.__audio._queue.put_nowait((new_frame, eventpoint))
        except queue.Full:
            try:
                self.__audio._queue.get_nowait()
            except queue.Empty:
                pass
            self.__audio._queue.put_nowait((new_frame, eventpoint))

    def get_buffer_size(self) -> int:
        return max(self.__video._queue.qsize(), self.__audio._queue.qsize() // 2)

    def notify(self, eventpoint):
        if self.__container is not None:
            self.__container.notify(eventpoint)

    @property
    def audio(self) -> MediaStreamTrack:
        return self.__audio

    @property
    def video(self) -> MediaStreamTrack:
        return self.__video

    def _start(self, track: PlayerStreamTrack) -> None:
        self.__started.add(track)
        if self.__thread is None:
            self.__log_debug("Iniciando hilo de renderizado del avatar")
            self.__thread_quit = threading.Event()
            self.__thread = threading.Thread(
                name="media-player",
                target=player_worker_thread,
                args=(
                    self.__thread_quit,
                    self.__container
                ),
                daemon=True
            )
            self.__thread.start()

    def _stop(self, track: PlayerStreamTrack) -> None:
        self.__started.discard(track)

        if not self.__started and self.__thread is not None:
            self.__log_debug("Deteniendo hilo de renderizado del avatar")
            if self.__thread_quit is not None:
                self.__thread_quit.set()
            if self.__thread is not None:
                self.__thread.join(timeout=2.0)
            self.__thread = None

        if not self.__started and self.__container is not None:
            self.__container = None

    def __log_debug(self, msg: str, *args) -> None:
        mylogger.debug(f"HumanPlayer {msg}", *args)

