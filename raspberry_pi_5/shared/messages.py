from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from shared.state import StreamerState


class MessageType(StrEnum):
    AUTH_REQUEST = "AUTH_REQUEST"
    AUTH_CHALLENGE = "AUTH_CHALLENGE"
    AUTH_RESPONSE = "AUTH_RESPONSE"
    AUTH_OK = "AUTH_OK"
    AUTH_FAILED = "AUTH_FAILED"
    START_STREAM = "START_STREAM"
    STOP_STREAM = "STOP_STREAM"
    HEARTBEAT = "HEARTBEAT"
    STATE = "STATE"
    ERROR = "ERROR"
    LOG = "LOG"


@dataclass(slots=True)
class ControlMessage:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "payload": self.payload,
                "request_id": self.request_id,
                "timestamp": self.timestamp,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> ControlMessage:
        data = json.loads(raw)
        return cls(
            type=str(data["type"]),
            payload=dict(data.get("payload") or {}),
            request_id=str(data.get("request_id") or uuid4().hex),
            timestamp=float(data.get("timestamp") or time.time()),
        )


def state_message(state: StreamerState, **extra: Any) -> ControlMessage:
    return ControlMessage(
        type=MessageType.STATE.value,
        payload={"state": state.value, **extra},
    )


def error_message(code: str, message: str) -> ControlMessage:
    return ControlMessage(
        type=MessageType.ERROR.value,
        payload={"code": code, "message": message},
    )
