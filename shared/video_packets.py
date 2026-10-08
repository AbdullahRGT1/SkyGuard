from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

MAGIC = b"SSV1"
MAX_UDP_PAYLOAD = 1200
HEADER = struct.Struct("!4sIHH")


@dataclass(frozen=True, slots=True)
class VideoPacket:
    frame_id: int
    chunk_index: int
    chunk_count: int
    payload: bytes


def iter_frame_packets(frame_id: int, frame_bytes: bytes) -> Iterator[bytes]:
    chunk_count = max(1, (len(frame_bytes) + MAX_UDP_PAYLOAD - 1) // MAX_UDP_PAYLOAD)
    if chunk_count > 65_535:
        raise ValueError("Encoded frame is too large for UDP packetization.")

    for chunk_index in range(chunk_count):
        start = chunk_index * MAX_UDP_PAYLOAD
        payload = frame_bytes[start : start + MAX_UDP_PAYLOAD]
        yield HEADER.pack(MAGIC, frame_id, chunk_index, chunk_count) + payload


def parse_packet(data: bytes) -> VideoPacket | None:
    if len(data) <= HEADER.size:
        return None

    magic, frame_id, chunk_index, chunk_count = HEADER.unpack(data[: HEADER.size])
    if magic != MAGIC or chunk_count < 1 or chunk_index >= chunk_count:
        return None

    return VideoPacket(
        frame_id=frame_id,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        payload=data[HEADER.size :],
    )
