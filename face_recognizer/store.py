from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True, slots=True)
class PendingObservation:
    id: int
    event_id: int
    image_path: Path
    timestamp: float
    violation_type: str
    violations: dict[str, int]
    embedding: list[float]
    bbox: tuple[int, int, int, int]
    quality: float
    face_area: float
    confidence: float
    provider: str


class SmartAlertStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add_event(
        self,
        *,
        image_path: Path,
        timestamp: float,
        violation_summary: str,
        violations: dict[str, int],
        observations: Iterable[dict],
    ) -> int:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO alert_events
                    (image_path, timestamp, violation_summary, violations_json, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    str(image_path),
                    timestamp,
                    violation_summary,
                    json.dumps(violations, separators=(",", ":")),
                ),
            )
            event_id = int(cursor.lastrowid)
            violation_key = _violation_key(violations)
            rows = []
            for observation in observations:
                rows.append(
                    (
                        event_id,
                        str(image_path),
                        timestamp,
                        violation_key,
                        json.dumps(violations, separators=(",", ":")),
                        json.dumps(observation["embedding"], separators=(",", ":")),
                        json.dumps(observation["bbox"], separators=(",", ":")),
                        float(observation["quality"]),
                        float(observation["face_area"]),
                        float(observation["confidence"]),
                        str(observation["provider"]),
                        "pending",
                    )
                )
            conn.executemany(
                """
                INSERT INTO face_observations
                    (event_id, image_path, timestamp, violation_type, violations_json,
                     embedding_json, bbox_json, quality, face_area, confidence, provider, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            return event_id

    def pending_observations(self) -> list[PendingObservation]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, event_id, image_path, timestamp, violation_type, violations_json,
                       embedding_json, bbox_json, quality, face_area, confidence, provider
                FROM face_observations
                WHERE status = 'pending'
                ORDER BY timestamp ASC
                """
            ).fetchall()

        observations_by_face: dict[tuple[int, str, str], PendingObservation] = {}
        for row in rows:
            event_id = int(row["event_id"])
            image_path = Path(str(row["image_path"]))
            bbox_json = str(row["bbox_json"] or "[0,0,0,0]")
            violations = dict(json.loads(row["violations_json"] or "{}"))
            key = (event_id, str(image_path), bbox_json)
            existing = observations_by_face.get(key)
            if existing is not None:
                merged = dict(existing.violations)
                for name, count in violations.items():
                    merged[name] = max(int(merged.get(name, 0)), int(count))
                observations_by_face[key] = PendingObservation(
                    id=existing.id,
                    event_id=existing.event_id,
                    image_path=existing.image_path,
                    timestamp=existing.timestamp,
                    violation_type=_violation_key(merged),
                    violations=merged,
                    embedding=existing.embedding,
                    bbox=existing.bbox,
                    quality=max(existing.quality, float(row["quality"] or 0.0)),
                    face_area=max(existing.face_area, float(row["face_area"] or 0.0)),
                    confidence=max(existing.confidence, float(row["confidence"] or 0.0)),
                    provider=existing.provider,
                )
                continue

            observations_by_face[key] = PendingObservation(
                id=int(row["id"]),
                event_id=event_id,
                image_path=image_path,
                timestamp=float(row["timestamp"]),
                violation_type=_violation_key(violations),
                violations=violations,
                embedding=list(json.loads(row["embedding_json"] or "[]")),
                bbox=tuple(json.loads(bbox_json)),
                quality=float(row["quality"] or 0.0),
                face_area=float(row["face_area"] or 0.0),
                confidence=float(row["confidence"] or 0.0),
                provider=str(row["provider"] or ""),
            )
        return list(observations_by_face.values())

    def mark_sent(self, observation_ids: Iterable[int]) -> None:
        ids = [int(value) for value in observation_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE face_observations SET status = 'sent', sent_at = ? WHERE id IN ({placeholders})",
                [now, *ids],
            )
            conn.execute(
                """
                UPDATE alert_events
                SET status = 'sent', sent_at = ?
                WHERE id IN (
                    SELECT event_id FROM face_observations
                    WHERE id IN (
                """
                + placeholders
                + "))",
                [now, *ids],
            )
            conn.commit()

    def mark_events_sent(self, event_ids: Iterable[int]) -> None:
        ids = [int(value) for value in set(event_ids)]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE face_observations SET status = 'sent', sent_at = ? WHERE event_id IN ({placeholders})",
                [now, *ids],
            )
            conn.execute(
                f"UPDATE alert_events SET status = 'sent', sent_at = ? WHERE id IN ({placeholders})",
                [now, *ids],
            )
            conn.commit()

    def prune_sent_records(self, older_than_seconds: int = 86_400) -> None:
        cutoff = time.time() - older_than_seconds
        with closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM face_observations WHERE status = 'sent' AND sent_at < ?",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM alert_events WHERE status = 'sent' AND sent_at < ?",
                (cutoff,),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_path TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    violation_summary TEXT NOT NULL,
                    violations_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sent_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS face_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    violation_type TEXT NOT NULL,
                    violations_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    bbox_json TEXT NOT NULL,
                    quality REAL NOT NULL,
                    face_area REAL NOT NULL,
                    confidence REAL NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sent_at REAL,
                    FOREIGN KEY(event_id) REFERENCES alert_events(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_face_obs_status ON face_observations(status, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_face_obs_violation ON face_observations(violation_type)"
            )
            conn.commit()


def _violation_key(violations: dict[str, int]) -> str:
    names = sorted(str(name) for name, count in violations.items() if int(count) > 0)
    return "+".join(names) if names else "UNKNOWN"
