from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from shared.settings import ViolationCaptureSettings

FACE_CLASSES = ("Mask", "NO-Mask")
CAPTURE_VIOLATION_CLASSES = ("NO-Mask", "NO-Helmet", "NO-Safety Vest")


class ViolationCaptureManager:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._settings = ViolationCaptureSettings()
        self._last_captured_face_count: int | None = None
        self._pending_face_count: int | None = None
        self._pending_started_at = 0.0
        self._inactive_started_at: float | None = None

    def configure(self, settings: ViolationCaptureSettings) -> None:
        self._settings = settings
        self.reset()

    def reset(self) -> None:
        self._last_captured_face_count = None
        self._pending_face_count = None
        self._pending_started_at = 0.0
        self._inactive_started_at = None

    def consider(
        self,
        image: QImage,
        class_counts: dict[str, int],
        violation_summary: str,
    ) -> Path | None:
        if not self._settings.enabled:
            return None

        now = time.monotonic()
        face_count = self._count_classes(class_counts, FACE_CLASSES)
        if face_count <= 0 or not self._has_capture_violation(class_counts):
            self._mark_inactive(now)
            return None

        if self._inactive_started_at is not None:
            inactive_for = now - self._inactive_started_at
            if inactive_for >= self._settings.stabilization_seconds:
                self.reset()
        self._inactive_started_at = None

        if self._last_captured_face_count is None:
            return self._capture(image, face_count, violation_summary)

        if face_count == self._last_captured_face_count:
            self._pending_face_count = None
            self._pending_started_at = 0.0
            return None

        if self._pending_face_count != face_count:
            if self._settings.stabilization_seconds <= 0:
                return self._capture(image, face_count, violation_summary)
            self._pending_face_count = face_count
            self._pending_started_at = now
            return None

        if now - self._pending_started_at < self._settings.stabilization_seconds:
            return None

        return self._capture(image, face_count, violation_summary)

    def _mark_inactive(self, now: float) -> None:
        self._pending_face_count = None
        self._pending_started_at = 0.0

        if self._last_captured_face_count is None:
            return

        if self._settings.stabilization_seconds <= 0:
            self.reset()
            return

        if self._inactive_started_at is None:
            self._inactive_started_at = now
            return

        if now - self._inactive_started_at >= self._settings.stabilization_seconds:
            self.reset()

    def _capture(self, image: QImage, face_count: int, violation_summary: str) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / self._file_name(face_count, violation_summary)
        if not image.save(str(path), "JPG", 95):
            raise RuntimeError(f"Could not save violation image: {path}")

        self._last_captured_face_count = face_count
        self._pending_face_count = None
        self._pending_started_at = 0.0
        return path

    @staticmethod
    def _count_classes(class_counts: dict[str, int], class_names: tuple[str, ...]) -> int:
        return sum(int(class_counts.get(class_name, 0)) for class_name in class_names)

    @staticmethod
    def _has_capture_violation(class_counts: dict[str, int]) -> bool:
        return any(
            int(class_counts.get(class_name, 0)) > 0
            for class_name in CAPTURE_VIOLATION_CLASSES
        )

    @staticmethod
    def _file_name(face_count: int, violation_summary: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        violations = ViolationCaptureManager._safe_name(violation_summary) or "violation"
        return f"{timestamp}_faces{face_count}_{violations}_raw.jpg"

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = []
        for char in value:
            if char.isalnum():
                cleaned.append(char)
            elif char in {"-", "_"}:
                cleaned.append(char)
            elif char in {",", " "}:
                cleaned.append("_")
        return "".join(cleaned).strip("_")[:80]
