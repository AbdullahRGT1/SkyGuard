from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from shared.settings import VideoSettings
from shared.video_packets import iter_frame_packets


@dataclass(frozen=True, slots=True)
class StreamTarget:
    host: str
    port: int


class StreamService:
    """Owns the camera/encoder/video pipeline lifecycle for Raspberry Pi (V4L2).

    The camera is opened inside `start()` only, after an authenticated START_STREAM command.
    """

    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._running = False
        self._target: StreamTarget | None = None
        self._camera = None
        self._socket: socket.socket | None = None
        self._process: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_id = 0
        self._default_video_settings = VideoSettings.from_env()
        self._video_settings = self._default_video_settings

    @property
    def running(self) -> bool:
        return self._running

    @property
    def video_settings(self) -> VideoSettings:
        return self._video_settings

    async def start(
        self,
        target: StreamTarget,
        video_settings: VideoSettings | None = None,
    ) -> None:
        if self._running:
            self._log("Stream start ignored because media pipeline is already running.")
            return

        requested_settings = video_settings or self._default_video_settings
        self._target = target
        self._video_settings = self._resolve_video_settings(requested_settings)
        self._log(f"Opening camera for requested target {target.host}:{target.port}.")

        try:
            if self._video_settings.codec == "h264":
                self._start_h264_process()
            else:
                self._open_mjpeg_sender()
        except Exception as exc:
            self._release_resources()
            if self._video_settings.codec != "h264":
                raise
            self._log(f"H.264 startup failed ({exc}); falling back to MJPEG.")
            self._video_settings = replace(requested_settings, codec="mjpeg")
            self._open_mjpeg_sender()

        self._stop_event.clear()
        self._running = True
        if self._video_settings.codec == "mjpeg":
            self._worker = threading.Thread(
                target=self._send_loop,
                name="streamer-video-sender",
                daemon=True,
            )
            self._worker.start()
        self._log("Camera and UDP video sender are live.")

    async def stop(self) -> None:
        if not self._running and self._target is None:
            return

        self._log("Stopping video sender.")
        self._running = False
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
        self._release_resources()
        self._worker = None
        self._stop_event.clear()
        self._running = False
        self._target = None
        self._log("Streamer returned to ready mode.")

    def _resolve_video_settings(self, settings: VideoSettings) -> VideoSettings:
        if settings.codec == "mjpeg":
            return settings

        if self._camera_command():
            return replace(settings, codec="h264")

        if settings.codec == "h264":
            self._log("rpicam-vid was not found; using MJPEG fallback.")
        return replace(settings, codec="mjpeg")

    def _open_mjpeg_sender(self) -> None:
        self._open_camera()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_048_576)

    def _start_h264_process(self) -> None:
        command_path = self._camera_command()
        if not command_path:
            raise RuntimeError("rpicam-vid was not found.")
        if self._target is None:
            raise RuntimeError("Stream target was not configured.")

        settings = self._video_settings
        target = self._target
        command = [
            command_path,
            "-t",
            "0",
            "-n",
            "--camera",
            str(settings.camera_index),
            "--width",
            str(settings.width),
            "--height",
            str(settings.height),
            "--framerate",
            str(settings.fps),
            "--codec",
            "libav",
            "--libav-format",
            "mpegts",
            "--low-latency",
            "--bitrate",
            str(settings.h264_bitrate_kbps * 1000),
            "-o",
            f"udp://{target.host}:{target.port}?pkt_size=1316",
        ]

        self._log(
            "Starting Raspberry Pi H.264/MPEG-TS stream "
            f"at {settings.width}x{settings.height}@{settings.fps}, "
            f"{settings.h264_bitrate_kbps} kbps."
        )
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.35)
        exit_code = self._process.poll()
        if exit_code is not None:
            self._process = None
            raise RuntimeError(f"rpicam-vid exited early with code {exit_code}.")

    @staticmethod
    def _camera_command() -> str | None:
        return shutil.which("rpicam-vid") or shutil.which("libcamera-vid")

    def _open_camera(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV is not installed. Run: pip install -r requirements.txt"
            ) from exc

        settings = self._video_settings
        # Using V4L2 backend by default for Linux/Raspberry Pi
        v4l2 = getattr(cv2, "CAP_V4L2", 200)
        camera = cv2.VideoCapture(settings.camera_index, v4l2)

        # Fallback to default if V4L2 fails
        if not camera.isOpened():
            self._log(
                "Warning: V4L2 backend failed for camera "
                f"{settings.camera_index}, falling back to default."
            )
            camera.release()
            camera = cv2.VideoCapture(settings.camera_index)

        if not camera.isOpened():
            raise RuntimeError(
                f"Camera {settings.camera_index} could not be opened. "
                "Check camera permissions, device usage, or SKYGUARD_CAMERA_INDEX."
            )

        # We try to set the requested format, some USB cameras may not support all configs
        # and OpenCV will pick the closest supported format
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
        camera.set(cv2.CAP_PROP_FPS, settings.fps)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Read one frame to verify it's working
        ok, _frame = camera.read()
        if not ok:
            camera.release()
            raise RuntimeError("Camera opened but did not return frames.")

        actual_w = camera.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps = camera.get(cv2.CAP_PROP_FPS)

        self._camera = camera
        self._log(
            "Camera opened. "
            f"Requested: {settings.width}x{settings.height}@{settings.fps}. "
            f"Actual: {int(actual_w)}x{int(actual_h)}@{actual_fps}."
        )

    def _send_loop(self) -> None:
        try:
            import cv2
        except ImportError:
            self._log("OpenCV disappeared after camera startup; stopping video sender.")
            return

        last_error_log = 0.0
        frame_interval = 1 / max(1, self._video_settings.fps)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._video_settings.jpeg_quality]

        while not self._stop_event.is_set():
            started_at = time.perf_counter()
            camera = self._camera
            sock = self._socket
            target = self._target
            if camera is None or sock is None or target is None:
                break
            target_address = (target.host, target.port)

            ok, frame = camera.read()
            if not ok:
                now = time.monotonic()
                if now - last_error_log > 1:
                    self._log("Camera frame read failed; retrying.")
                    last_error_log = now
                time.sleep(0.02)
                continue

            success, encoded = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                continue

            self._frame_id = (self._frame_id + 1) % 4_294_967_295
            frame_bytes = encoded.tobytes()
            try:
                for packet in iter_frame_packets(self._frame_id, frame_bytes):
                    sock.sendto(packet, target_address)
            except OSError as exc:
                self._log(f"UDP video send failed: {exc}")
                break

            elapsed = time.perf_counter() - started_at
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

    def _release_resources(self) -> None:
        if self._camera is not None:
            self._camera.release()
            self._camera = None

        if self._socket is not None:
            self._socket.close()
            self._socket = None

        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            self._process = None
