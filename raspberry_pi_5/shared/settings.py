from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

RESOLUTION_PRESETS = ("640x360", "1280x720", "1920x1080", "Custom")
VIDEO_CODECS = ("auto", "mjpeg", "h264")


def _env(name: str, default: str) -> str:
    legacy_name = name.replace("SKYGUARD_", "SIMPLE_STREAM_", 1)
    return os.getenv(name, os.getenv(legacy_name, default))


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_video_codec(value: Any, default: str = "auto") -> str:
    codec = str(value or default).strip().lower()
    if codec in {"h.264", "avc"}:
        codec = "h264"
    return codec if codec in VIDEO_CODECS else default


@dataclass(frozen=True, slots=True)
class VideoSettings:
    camera_index: int = 0
    width: int = 640
    height: int = 360
    fps: int = 60
    jpeg_quality: int = 65
    codec: str = "auto"
    h264_bitrate_kbps: int = 2500

    @classmethod
    def from_env(cls) -> VideoSettings:
        return cls(
            camera_index=_as_int(_env("SKYGUARD_CAMERA_INDEX", "0"), 0),
            width=_as_int(_env("SKYGUARD_FRAME_WIDTH", "640"), 640),
            height=_as_int(_env("SKYGUARD_FRAME_HEIGHT", "360"), 360),
            fps=_as_int(_env("SKYGUARD_FPS", "60"), 60),
            jpeg_quality=_as_int(_env("SKYGUARD_JPEG_QUALITY", "65"), 65),
            codec=_as_video_codec(_env("SKYGUARD_VIDEO_CODEC", "auto")),
            h264_bitrate_kbps=_as_int(
                _env("SKYGUARD_H264_BITRATE_KBPS", "2500"),
                2500,
            ),
        ).validated()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> VideoSettings:
        if not data:
            return cls.from_env()

        return cls(
            camera_index=_as_int(data.get("camera_index"), 0),
            width=_as_int(data.get("width"), 640),
            height=_as_int(data.get("height"), 360),
            fps=_as_int(data.get("fps"), 60),
            jpeg_quality=_as_int(data.get("jpeg_quality"), 65),
            codec=_as_video_codec(data.get("codec") or _env("SKYGUARD_VIDEO_CODEC", "auto")),
            h264_bitrate_kbps=_as_int(data.get("h264_bitrate_kbps"), 2500),
        ).validated()

    def validated(self) -> VideoSettings:
        if self.camera_index < 0:
            raise ValueError("camera_index must be 0 or greater.")
        if not 160 <= self.width <= 3840:
            raise ValueError("width must be between 160 and 3840.")
        if not 120 <= self.height <= 2160:
            raise ValueError("height must be between 120 and 2160.")
        if not 1 <= self.fps <= 60:
            raise ValueError("fps must be between 1 and 60.")
        if not 30 <= self.jpeg_quality <= 95:
            raise ValueError("jpeg_quality must be between 30 and 95.")
        if self.codec not in VIDEO_CODECS:
            raise ValueError("codec must be auto, mjpeg, or h264.")
        if not 256 <= self.h264_bitrate_kbps <= 50_000:
            raise ValueError("h264_bitrate_kbps must be between 256 and 50000.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_index": self.camera_index,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "jpeg_quality": self.jpeg_quality,
            "codec": self.codec,
            "h264_bitrate_kbps": self.h264_bitrate_kbps,
        }

    @property
    def resolution_text(self) -> str:
        value = f"{self.width}x{self.height}"
        return value if value in RESOLUTION_PRESETS else "Custom"
