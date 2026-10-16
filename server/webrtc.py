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
    A video/audio track that returns animated frames synchronized with WebRTC.
    """

    def __init__(self, player, kind):
        super().__init__()
        self.kind = kind
        self._player = player
        # Video: buffer de 100 frames (4.0s @ 25fps)
        # Audio: buffer simétrico de 200 frames (4.0s @ 50 chunks/s de 20ms)
        # Ratio exacto 1:2 para sincronización absoluta de audio y video
        if self.kind == 'video':
            self._queue = queue.Queue(maxsize=100)
        else:
            self._queue = queue.Queue(maxsize=200)
        self.timelist = []
        self.current_frame_count = 0
        self._last_frame = None
        if self.kind == 'video':
            self.framecount = 0
            self.lasttime = time.perf_counter()
            self.totaltime = 0
    
    _start: float
    _timestamp: int

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        if self.readyState != "live":
            raise Exception("Track is no longer live")

        if self.kind == 'video':
            if hasattr(self, "_timestamp"):
                self._timestamp += int(VIDEO_PTIME * VIDEO_CLOCK_RATE)
                self.current_frame_count += 1
                wait = self._start + self.current_frame_count * VIDEO_PTIME - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
            else:
                if self._player and getattr(self._player, "_shared_start", None) is not None:
                    self._start = self._player._shared_start
                else:
                    self._start = time.time()
                    if self._player:
                        self._player._shared_start = self._start
                self._timestamp = 0
                self.current_frame_count = 0
                self.timelist.append(self._start)
                mylogger.info('video start:%f', self._start)
            return self._timestamp, VIDEO_TIME_BASE
        else: # audio
            if hasattr(self, "_timestamp"):
                self._timestamp += int(AUDIO_PTIME * SAMPLE_RATE)
                self.current_frame_count += 1
                wait = self._start + self.current_frame_count * AUDIO_PTIME - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
            else:
                if self._player and getattr(self._player, "_shared_start", None) is not None:
                    self._start = self._player._shared_start
                else:
                    self._start = time.time()
                    if self._player:
                        self._player._shared_start = self._start
                self._timestamp = 0
                self.current_frame_count = 0
                self.timelist.append(self._start)
                mylogger.info('audio start:%f', self._start)
            return self._timestamp, AUDIO_TIME_BASE

    async def recv(self) -> Union[Frame, Packet]:
        if self.readyState != "live":
            raise Exception("Track stopped")

        self._player._start(self)

        frame = None
        eventpoint = None

        while self.readyState == "live":
            try:
                frame, eventpoint = self._queue.get_nowait()
                break
            except queue.Empty:
                if self.kind == 'video':
                    if self._last_frame is not None:
                        frame = self._last_frame
                        break
                else:
                    silence_samples = int(AUDIO_PTIME * SAMPLE_RATE)  # 320 samples (20ms @ 16kHz)
                    frame = AudioFrame(format='s16', layout='mono', samples=silence_samples)
                    frame.planes[0].update(np.zeros(silence_samples, dtype=np.int16).tobytes())
                    frame.sample_rate = SAMPLE_RATE
                    break
                await asyncio.sleep(0.01)

        if self.readyState != "live" or frame is None:
            raise Exception("Track stopped")

        if self.kind == 'video':
            self._last_frame = frame

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
                mylogger.info(f"------actual avg final fps:{self.framecount/self.totaltime:.4f}")
                self.framecount = 0
                self.totaltime = 0

        return frame
    
    def purge(self, keep_last=False):
        """Purga frames pendientes en cola para corte inmediato."""
        with self._queue.mutex:
            if keep_last and len(self._queue.queue) > 1:
                last_item = self._queue.queue[-1]
                self._queue.queue.clear()
                self._queue.queue.append(last_item)
            else:
                self._queue.queue.clear()

    def stop(self):
        super().stop()
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                del item
            except queue.Empty:
                break
        if self._player is not None:
            self._player._stop(self)
            self._player = None

def player_worker_thread(
    quit_event,
    container
):
    container.render(quit_event)

class HumanPlayer:

    def __init__(
        self, avatar_session, format=None, options=None, timeout=None, loop=False, decode=True
    ):
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None
        self._shared_start: Optional[float] = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__audio = PlayerStreamTrack(self, kind="audio")
        self.__video = PlayerStreamTrack(self, kind="video")

        self.__container = avatar_session
        if hasattr(self.__container, 'output'):
            self.__container.output._player = self

        if hasattr(self.__container, 'frame_list_cycle') and len(self.__container.frame_list_cycle) > 0:
            from av import VideoFrame
            self.__video._last_frame = VideoFrame.from_ndarray(self.__container.frame_list_cycle[0], format="bgr24")

    def purge(self):
        """Purga buffers de audio y video WebRTC de forma sincronizada a 0 items.
        VideoTrack utiliza su _last_frame interno en caso de cola vacía, evitando
        pantalla negra y garantizando que los nuevos frames de A/V arranquen en t=0 exacto."""
        if self.__audio:
            self.__audio.purge(keep_last=False)
        if self.__video:
            self.__video.purge(keep_last=False)

    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        if self.__video is None:
            return
        try:
            self.__video._queue.put_nowait((new_frame, None))
        except queue.Full:
            # Descarte simétrico en caso de congestión de red: 1 frame de video + 2 chunks de audio
            try:
                self.__video._queue.get_nowait()
            except queue.Empty:
                pass
            if self.__audio:
                for _ in range(2):
                    try:
                        self.__audio._queue.get_nowait()
                    except queue.Empty:
                        break
            try:
                self.__video._queue.put_nowait((new_frame, None))
            except queue.Full:
                pass

    def push_audio(self, frame, eventpoint=None):
        from av import AudioFrame
        new_frame = AudioFrame(format='s16', layout='mono', samples=frame.shape[0])
        new_frame.planes[0].update(frame.tobytes())
        new_frame.sample_rate = 16000
        if self.__audio is None:
            return
        try:
            self.__audio._queue.put_nowait((new_frame, eventpoint))
        except queue.Full:
            # Descarte simétrico: 2 chunks de audio + 1 frame de video
            try:
                self.__audio._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.__audio._queue.get_nowait()
            except queue.Empty:
                pass
            if self.__video:
                try:
                    self.__video._queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self.__audio._queue.put_nowait((new_frame, eventpoint))
            except queue.Full:
                pass

    def get_buffer_size(self) -> int:
        v_size = self.__video._queue.qsize() if self.__video else 0
        a_size = (self.__audio._queue.qsize() // 2) if self.__audio else 0
        return max(v_size, a_size)

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
            self.__log_debug("Starting worker thread")
            self.__thread_quit = threading.Event()
            self.__thread = threading.Thread(
                name="media-player",
                target=player_worker_thread,
                args=(
                    self.__thread_quit,
                    self.__container
                ),
            )
            self.__thread.start()

    def _stop(self, track: PlayerStreamTrack) -> None:
        self.__started.discard(track)

        if not self.__started and self.__thread is not None:
            self.__log_debug("Stopping worker thread")
            self.__thread_quit.set()
            self.__thread.join()
            self.__thread = None

        if not self.__started and self.__container is not None:
            #self.__container.close()
            self.__container = None

    def __log_debug(self, msg: str, *args) -> None:
        mylogger.debug(f"HumanPlayer {msg}", *args)
