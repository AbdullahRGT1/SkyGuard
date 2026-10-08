from __future__ import annotations

import os
from dataclasses import dataclass

from shared.constants import (
    CONTROL_PORT,
    DEFAULT_CONTROL_HOST,
    DEFAULT_DEV_PIN,
    VIDEO_PORT,
)
from shared.security import PinRecord, create_pin_record


def _env(name: str, default: str) -> str:
    legacy_name = name.replace("SKYGUARD_", "SIMPLE_STREAM_", 1)
    return os.getenv(name, os.getenv(legacy_name, default))


@dataclass(frozen=True, slots=True)
class StreamerConfig:
    control_host: str = DEFAULT_CONTROL_HOST
    control_port: int = CONTROL_PORT
    video_port: int = VIDEO_PORT
    pin_record: PinRecord = create_pin_record(DEFAULT_DEV_PIN)

    @classmethod
    def from_env(cls) -> StreamerConfig:
        pin = _env("SKYGUARD_PIN", DEFAULT_DEV_PIN)
        return cls(
            control_host=_env("SKYGUARD_CONTROL_HOST", DEFAULT_CONTROL_HOST),
            control_port=int(_env("SKYGUARD_CONTROL_PORT", str(CONTROL_PORT))),
            video_port=int(_env("SKYGUARD_VIDEO_PORT", str(VIDEO_PORT))),
            pin_record=create_pin_record(pin),
        )
