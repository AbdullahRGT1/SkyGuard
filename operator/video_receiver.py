from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from shared.video_packets import parse_packet

STALE_FRAME_SECONDS = 0.5
MAX_PENDING_FRAMES = 8
STALE_SWEEP_SECONDS = 0.25


class VideoReceiver(QObject):
    frame_received = Signal(QImage)
    status_changed = Signal(str)

    def __init__(self, log: Callable[[str], None]) -> None:
        super().__init__()
        self._log = log
        self._socket: socket.socket | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._codec = "mjpeg"

    @property
    def running(self) -> bool:
        return self._running

    def start(self, port: int, codec: str = "mjpeg") -> None:
        if self._running:
            return

        self._codec = self._normalize_codec(codec)
        self._stop_event.clear()
        self._running = True
        self._worker = threading.Thread(
            target=self._receive_loop,
            args=(port, self._codec),
            name="operator-video-receiver",
            daemon=True,
        )
        self._worker.start()
        self.status_changed.emit("WAITING_FOR_VIDEO")
        self._log(f"Video receiver listening on UDP 0.0.0.0:{port} ({self._codec}).")

    def stop(self) -> None:
        if not self._running:
            return

        self._stop_event.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1)
        self._worker = None
        self._running = False
        self.status_changed.emit("NO_SIGNAL")
        self._log("Video receiver stopped.")

    def _receive_loop(self, port: int, codec: str) -> None:
        if codec == "h264":
            self._receive_h264_loop(port)
            return
        self._receive_mjpeg_loop(port)

    def _receive_mjpeg_loop(self, port: int) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            self._log("OpenCV/numpy is not installed. Run: pip install -r requirements.txt")
            self._running = False
            self.status_changed.emit("VIDEO_ERROR")
            return

        frames: dict[int, dict[int, bytes]] = {}
        seen_at: dict[int, float] = {}
        last_stale_sweep = time.monotonic()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4_194_304)
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.5)
            self._socket = sock
        except OSError as exc:
            self._log(f"Could not bind UDP video port {port}: {exc}")
            self._running = False
            self.status_changed.emit("VIDEO_ERROR")
            return

        while not self._stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(65_535)
            except TimeoutError:
                self._drop_stale_frames(frames, seen_at)
                continue
            except OSError:
                break

            now = time.monotonic()
            if now - last_stale_sweep >= STALE_SWEEP_SECONDS:
                self._drop_stale_frames(frames, seen_at, now)
                self._trim_pending_frames(frames, seen_at)
                last_stale_sweep = now

            packet = parse_packet(data)
            if packet is None:
                continue

            chunks = frames.setdefault(packet.frame_id, {})
            chunks[packet.chunk_index] = packet.payload
            seen_at[packet.frame_id] = now

            if len(chunks) != packet.chunk_count:
                continue

            frame_bytes = b"".join(chunks[index] for index in range(packet.chunk_count))
            frames.pop(packet.frame_id, None)
            seen_at.pop(packet.frame_id, None)

            encoded = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            self.frame_received.emit(self._bgr_frame_to_qimage(frame, cv2))

    def _receive_h264_loop(self, port: int) -> None:
        try:
            import cv2
        except ImportError:
            self._log("OpenCV is not installed. Run: pip install -r requirements.txt")
            self._running = False
            self.status_changed.emit("VIDEO_ERROR")
            return

        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "fflags;nobuffer|flags;low_delay|framedrop;1",
        )
        url = f"udp://@:{port}?fifo_size=1000000&overrun_nonfatal=1"
        backend = getattr(cv2, "CAP_FFMPEG", 0)
        capture = cv2.VideoCapture(url, backend) if backend else cv2.VideoCapture(url)
        last_wait_log = 0.0

        try:
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    now = time.monotonic()
                    if now - last_wait_log > 2:
                        self._log("Waiting for H.264 video packets.")
                        last_wait_log = now
                    time.sleep(0.02)
                    continue

                self.frame_received.emit(self._bgr_frame_to_qimage(frame, cv2))
        finally:
            capture.release()

    @staticmethod
    def _drop_stale_frames(
        frames: dict[int, dict[int, bytes]],
        seen_at: dict[int, float],
        now: float | None = None,
    ) -> None:
        now = now or time.monotonic()
        stale_ids = [
            frame_id
            for frame_id, timestamp in seen_at.items()
            if now - timestamp > STALE_FRAME_SECONDS
        ]
        for frame_id in stale_ids:
            frames.pop(frame_id, None)
            seen_at.pop(frame_id, None)

    @staticmethod
    def _trim_pending_frames(
        frames: dict[int, dict[int, bytes]],
        seen_at: dict[int, float],
    ) -> None:
        overflow = len(frames) - MAX_PENDING_FRAMES
        if overflow <= 0:
            return

        oldest_ids = sorted(seen_at, key=seen_at.get)[:overflow]
        for frame_id in oldest_ids:
            frames.pop(frame_id, None)
            seen_at.pop(frame_id, None)

    @staticmethod
    def _normalize_codec(codec: str) -> str:
        normalized = codec.strip().lower()
        if normalized in {"h264", "h.264", "avc"}:
            return "h264"
        return "mjpeg"

    @staticmethod
    def _bgr_frame_to_qimage(frame, cv2_module) -> QImage:
        height, width, channels = frame.shape
        bgr_format = getattr(QImage.Format, "Format_BGR888", None)
        if bgr_format is not None:
            return QImage(
                frame.data,
                width,
                height,
                channels * width,
                bgr_format,
            ).copy()

        rgb_frame = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2RGB)
        return QImage(
            rgb_frame.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
