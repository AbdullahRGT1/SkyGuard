from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_AI_MODEL = "light_2.6k.pt"
RESOLUTION_PRESETS = ("640x360", "1280x720", "1920x1080", "Custom")
AI_DEVICES = ("auto", "cpu", "cuda")
VIDEO_CODECS = ("auto", "mjpeg", "h264")


def _env(name: str, default: str) -> str:
    legacy_name = name.replace("SKYGUARD_", "SIMPLE_STREAM_", 1)
    return os.getenv(name, os.getenv(legacy_name, default))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
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


@dataclass(frozen=True, slots=True)
class AiSettings:
    enabled: bool = False
    model_name: str = DEFAULT_AI_MODEL
    device: str = "auto"
    conf: float = 0.60
    iou: float = 0.40
    imgsz: int = 320
    verbose: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AiSettings:
        if not data:
            return cls()

        return cls(
            enabled=_as_bool(data.get("enabled"), False),
            model_name=str(data.get("model_name") or DEFAULT_AI_MODEL),
            device=str(data.get("device") or "auto"),
            conf=_as_float(data.get("conf"), 0.60),
            iou=_as_float(data.get("iou"), 0.40),
            imgsz=_as_int(data.get("imgsz"), 320),
            verbose=_as_bool(data.get("verbose"), False),
        ).validated()

    def validated(self) -> AiSettings:
        if self.device not in AI_DEVICES:
            raise ValueError("device must be auto, cpu, or cuda.")
        if not 0.01 <= self.conf <= 1.0:
            raise ValueError("conf must be between 0.01 and 1.0.")
        if not 0.01 <= self.iou <= 1.0:
            raise ValueError("iou must be between 0.01 and 1.0.")
        if not 160 <= self.imgsz <= 1280:
            raise ValueError("imgsz must be between 160 and 1280.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model_name": self.model_name,
            "device": self.device,
            "conf": self.conf,
            "iou": self.iou,
            "imgsz": self.imgsz,
            "verbose": self.verbose,
        }


@dataclass(frozen=True, slots=True)
class ViolationCaptureSettings:
    enabled: bool = False
    stabilization_seconds: float = 2.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ViolationCaptureSettings:
        if not data:
            return cls()

        return cls(
            enabled=_as_bool(data.get("enabled"), False),
            stabilization_seconds=_as_float(data.get("stabilization_seconds"), 2.0),
        ).validated()

    def validated(self) -> ViolationCaptureSettings:
        if not 0 <= self.stabilization_seconds <= 30:
            raise ValueError("stabilization_seconds must be between 0 and 30.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "stabilization_seconds": self.stabilization_seconds,
        }


@dataclass(frozen=True, slots=True)
class SmartAlertSettings:
    enabled: bool = False
    webhook_url: str = ""
    batch_interval_minutes: int = 5
    max_images_per_batch: int = 5
    face_similarity: float = 0.65
    group_similar_faces: bool = True
    send_summary: bool = True
    delete_temp_images: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SmartAlertSettings:
        if not data:
            return cls()

        return cls(
            enabled=_as_bool(data.get("enabled"), False),
            webhook_url=str(data.get("webhook_url") or ""),
            batch_interval_minutes=_as_int(data.get("batch_interval_minutes"), 5),
            max_images_per_batch=_as_int(data.get("max_images_per_batch"), 5),
            face_similarity=_as_float(data.get("face_similarity"), 0.65),
            group_similar_faces=_as_bool(data.get("group_similar_faces"), True),
            send_summary=_as_bool(data.get("send_summary"), True),
            delete_temp_images=_as_bool(data.get("delete_temp_images"), False),
        ).validated()

    def validated(self) -> SmartAlertSettings:
        if not 1 <= self.batch_interval_minutes <= 60:
            raise ValueError("batch_interval_minutes must be between 1 and 60.")
        if not 1 <= self.max_images_per_batch <= 10:
            raise ValueError("max_images_per_batch must be between 1 and 10.")
        if not 0.1 <= self.face_similarity <= 0.99:
            raise ValueError("face_similarity must be between 0.10 and 0.99.")
        if self.webhook_url and not self.webhook_url.lower().startswith(("http://", "https://")):
            raise ValueError("webhook_url must start with http:// or https://.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "webhook_url": self.webhook_url,
            "batch_interval_minutes": self.batch_interval_minutes,
            "max_images_per_batch": self.max_images_per_batch,
            "face_similarity": self.face_similarity,
            "group_similar_faces": self.group_similar_faces,
            "send_summary": self.send_summary,
            "delete_temp_images": self.delete_temp_images,
        }


@dataclass(frozen=True, slots=True)
class OperatorSettings:
    ai: AiSettings = field(default_factory=AiSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    violation_capture: ViolationCaptureSettings = field(
        default_factory=ViolationCaptureSettings
    )
    smart_alerts: SmartAlertSettings = field(default_factory=SmartAlertSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OperatorSettings:
        if not data:
            return cls()

        return cls(
            ai=AiSettings.from_dict(data.get("ai")),
            video=VideoSettings.from_dict(data.get("video")),
            violation_capture=ViolationCaptureSettings.from_dict(
                data.get("violation_capture")
            ),
            smart_alerts=SmartAlertSettings.from_dict(data.get("smart_alerts")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai": self.ai.to_dict(),
            "video": self.video.to_dict(),
            "violation_capture": self.violation_capture.to_dict(),
            "smart_alerts": self.smart_alerts.to_dict(),
        }
