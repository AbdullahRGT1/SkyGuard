from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

IMPROVED_CLASS_NAMES = (
    "Helmet",
    "Mask",
    "NO-Helmet",
    "NO-Mask",
    "NO-Safety Vest",
    "Person",
    "Safety Cone",
    "Safety Vest",
    "machinery",
    "vehicle",
)


@dataclass(frozen=True, slots=True)
class DetectionResult:
    frame: Any
    inference_ms: float
    fps: float
    violation_count: int
    violation_summary: str
    class_counts: dict[str, int]


class ImprovedYoloFrameProcessor:
    """Reusable version of the old live-camera demo.

    The original script opened a local camera at import time. This class keeps the same
    model settings, class names, and cvzone drawing style, but operates on frames that
    are already supplied by the operator video receiver.
    """

    def __init__(
        self,
        model: Any,
        cvzone_module: Any,
        *,
        class_names: tuple[str, ...] = IMPROVED_CLASS_NAMES,
    ) -> None:
        self._model = model
        self._cvzone = cvzone_module
        self._class_names = class_names

    def predict(
        self,
        frame_bgr: Any,
        *,
        imgsz: int = 320,
        iou: float = 0.4,
        conf: float = 0.6,
        verbose: bool = False,
        device: str | None = None,
    ) -> DetectionResult:
        started_at = time.perf_counter()
        results = self._model.predict(
            frame_bgr,
            imgsz=imgsz,
            iou=iou,
            conf=conf,
            verbose=verbose,
            device=device,
        )
        inference_ms = (time.perf_counter() - started_at) * 1000
        fps = 1000 / inference_ms if inference_ms > 0 else 0.0
        annotated, violation_count, violation_summary, class_counts = self.draw(
            frame_bgr,
            results[0],
            fps=fps,
        )
        return DetectionResult(
            frame=annotated,
            inference_ms=inference_ms,
            fps=fps,
            violation_count=violation_count,
            violation_summary=violation_summary,
            class_counts=class_counts,
        )

    def draw(
        self,
        frame_bgr: Any,
        result: Any,
        *,
        fps: float,
    ) -> tuple[Any, int, str, dict[str, int]]:
        annotated = frame_bgr.copy()
        violations: list[str] = []
        class_counts: dict[str, int] = {}

        for box in result.boxes:
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            class_name = self._class_name(cls)
            class_counts[class_name] = class_counts.get(class_name, 0) + 1
            is_violation = class_name.startswith("NO")
            color = (0, 0, 255) if is_violation else (255, 0, 0)
            if is_violation:
                violations.append(class_name)

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)
            label = f"{class_name} {conf:.2f}"

            self._cvzone.cornerRect(annotated, (x1, y1, width, height), 1, 1, 1, color)
            self._cvzone.putTextRect(
                annotated,
                label,
                (max(0, x1), max(20, y1)),
                1,
                1,
                (255, 255, 255),
                color,
            )

        self._cvzone.putTextRect(
            annotated,
            f"FPS: {fps:.1f}",
            (20, 40),
            1,
            1,
            (255, 255, 255),
            (0, 0, 0),
        )

        violation_summary = ", ".join(sorted(set(violations)))
        return annotated, len(violations), violation_summary, class_counts

    def _class_name(self, cls: int) -> str:
        if 0 <= cls < len(self._class_names):
            return self._class_names[cls]
        names = getattr(self._model, "names", {})
        if isinstance(names, dict):
            return str(names.get(cls, cls))
        if isinstance(names, (list, tuple)) and 0 <= cls < len(names):
            return str(names[cls])
        return str(cls)
