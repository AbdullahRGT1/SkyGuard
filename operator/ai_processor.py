from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from shared.settings import AiSettings

AI_ERROR_LOG_COOLDOWN_SECONDS = 5.0
AI_ERROR_DISABLE_THRESHOLD = 5
AI_ERROR_DISABLE_SECONDS = 15.0


class AiProcessor(QObject):
    frame_processed = Signal(QImage)
    detection_processed = Signal(QImage, object, int, str)
    status_changed = Signal(str)
    metrics_changed = Signal(str)
    violations_changed = Signal(int)
    log_received = Signal(str)

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._project_root = project_root
        self._settings = AiSettings()
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._latest_frame: QImage | None = None
        self._fatal_error = False
        self._ready = False
        self._last_violation_summary = ""
        self._detection_events_enabled = False
        self._processing_error_count = 0
        self._last_processing_error_log = 0.0
        self._disabled_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._settings.enabled and not self._fatal_error

    def configure(self, settings: AiSettings) -> None:
        self.stop()
        self._settings = settings
        self._fatal_error = False
        self._ready = False
        self._last_violation_summary = ""
        self._reset_processing_errors()

        if not settings.enabled:
            self.status_changed.emit("Disabled")
            self.metrics_changed.emit("RAW")
            self.violations_changed.emit(0)
            return

        self.status_changed.emit("Loading")
        self._ensure_worker()

    def submit_frame(self, image: QImage) -> bool:
        if not self.enabled or not self._ready:
            return False
        if self._is_in_cooldown():
            return False

        with self._lock:
            self._latest_frame = QImage(image)
        self._frame_event.set()
        return True

    def set_detection_events_enabled(self, enabled: bool) -> None:
        self._detection_events_enabled = enabled

    def stop(self) -> None:
        self._stop_event.set()
        self._frame_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
        self._worker = None
        self._stop_event.clear()
        with self._lock:
            self._latest_frame = None
        self._ready = False
        self._reset_processing_errors()

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run,
            name="operator-ai-processor",
            daemon=True,
        )
        self._worker.start()

    def _run(self) -> None:
        try:
            import cv2
            import cvzone
            import numpy as np
            import torch
            from ultralytics import YOLO

            from AI_layer.improved import ImprovedYoloFrameProcessor
        except ImportError as exc:
            self._fatal_error = True
            self._ready = False
            self.status_changed.emit("Missing dependencies")
            self.metrics_changed.emit("AI ERROR")
            self.log_received.emit(
                "AI dependencies are missing. Run setup_ai_cpu.ps1 or setup_ai_cuda.ps1."
            )
            self.log_received.emit(f"Missing dependency detail: {exc}")
            return

        settings = self._settings
        model_path = self._project_root / "AI_layer" / "yolo" / settings.model_name
        if not model_path.exists():
            self._fatal_error = True
            self._ready = False
            self.status_changed.emit("Model error")
            self.metrics_changed.emit("AI ERROR")
            self.log_received.emit(f"AI model was not found: {model_path}")
            return

        try:
            device = self._resolve_device(settings.device, torch)
            if settings.device == "cuda" and device == "cpu":
                self.log_received.emit("CUDA was requested but is unavailable; using CPU.")
            model = YOLO(str(model_path))
            processor = ImprovedYoloFrameProcessor(model, cvzone)
            warmup = np.zeros((settings.imgsz, settings.imgsz, 3), dtype=np.uint8)
            model.predict(
                warmup,
                imgsz=settings.imgsz,
                conf=settings.conf,
                iou=settings.iou,
                verbose=False,
                device=device,
            )
            self._ready = True
            self.status_changed.emit("Ready")
            self.metrics_changed.emit("AI ON")
            self.log_received.emit(f"AI model loaded: {model_path.name} on {device}.")
        except Exception as exc:
            self._fatal_error = True
            self._ready = False
            self.status_changed.emit("Model error")
            self.metrics_changed.emit("AI ERROR")
            self.log_received.emit(f"AI model failed to load: {exc}")
            return

        while not self._stop_event.is_set():
            self._frame_event.wait(timeout=0.5)
            self._frame_event.clear()
            if self._stop_event.is_set():
                break

            with self._lock:
                image = self._latest_frame
                self._latest_frame = None

            if image is None:
                continue

            current_settings = self._settings
            try:
                bgr_frame = self._qimage_to_bgr_array(image, np, cv2)
                detection = processor.predict(
                    bgr_frame,
                    imgsz=current_settings.imgsz,
                    iou=current_settings.iou,
                    conf=current_settings.conf,
                    verbose=current_settings.verbose,
                    device=device,
                )
                self._emit_violation_log(
                    detection.violation_count,
                    detection.violation_summary,
                )
                had_processing_errors = self._processing_error_count > 0
                self._reset_processing_errors()
                if had_processing_errors:
                    self.status_changed.emit("Ready")
                self.violations_changed.emit(detection.violation_count)
                if self._detection_events_enabled:
                    self.detection_processed.emit(
                        image,
                        dict(detection.class_counts),
                        detection.violation_count,
                        detection.violation_summary,
                    )
                self.metrics_changed.emit(
                    f"AI ON | {detection.inference_ms:.0f} ms | {detection.fps:.1f} FPS"
                )
                self.frame_processed.emit(
                    self._bgr_array_to_qimage(detection.frame, QImage, cv2)
                )
            except Exception as exc:
                self._handle_processing_error(exc)

    @staticmethod
    def _resolve_device(requested: str, torch_module) -> str:
        if requested == "cuda":
            if torch_module.cuda.is_available():
                return "cuda"
            return "cpu"
        if requested == "cpu":
            return "cpu"
        return "cuda" if torch_module.cuda.is_available() else "cpu"

    @staticmethod
    def _qimage_to_bgr_array(image: QImage, np_module, cv2_module):
        bgr_format = getattr(QImage.Format, "Format_BGR888", None)
        if bgr_format is not None:
            converted = image.convertToFormat(bgr_format)
            return AiProcessor._qimage_to_3channel_array(converted, np_module)

        converted = image.convertToFormat(QImage.Format.Format_RGB888)
        rgb_frame = AiProcessor._qimage_to_3channel_array(converted, np_module)
        return cv2_module.cvtColor(rgb_frame, cv2_module.COLOR_RGB2BGR)

    @staticmethod
    def _qimage_to_3channel_array(converted: QImage, np_module):
        width = converted.width()
        height = converted.height()
        bytes_per_line = converted.bytesPerLine()
        buffer = converted.constBits()
        array = np_module.frombuffer(
            buffer,
            dtype=np_module.uint8,
            count=height * bytes_per_line,
        ).reshape((height, bytes_per_line))
        return array[:, : width * 3].reshape((height, width, 3)).copy()

    @staticmethod
    def _bgr_array_to_qimage(bgr_frame, qimage_cls, cv2_module) -> QImage:
        height, width, channels = bgr_frame.shape
        bgr_format = getattr(qimage_cls.Format, "Format_BGR888", None)
        if bgr_format is not None:
            return qimage_cls(
                bgr_frame.data,
                width,
                height,
                channels * width,
                bgr_format,
            ).copy()

        rgb_frame = cv2_module.cvtColor(bgr_frame, cv2_module.COLOR_BGR2RGB)
        return qimage_cls(
            rgb_frame.data,
            width,
            height,
            channels * width,
            qimage_cls.Format.Format_RGB888,
        ).copy()

    def _emit_violation_log(self, count: int, summary: str) -> None:
        if count <= 0:
            self._last_violation_summary = ""
            return

        if summary and summary != self._last_violation_summary:
            self._last_violation_summary = summary
            self.log_received.emit(f"AI violation detected: {summary}")

    def _handle_processing_error(self, exc: Exception) -> None:
        now = time.monotonic()
        self._processing_error_count += 1

        if now - self._last_processing_error_log >= AI_ERROR_LOG_COOLDOWN_SECONDS:
            self._last_processing_error_log = now
            self.log_received.emit(
                "AI processing error "
                f"({self._processing_error_count}/{AI_ERROR_DISABLE_THRESHOLD}): {exc}"
            )

        if self._processing_error_count < AI_ERROR_DISABLE_THRESHOLD:
            self.status_changed.emit("Model error")
            self.metrics_changed.emit("AI ERROR")
            return

        self._disabled_until = now + AI_ERROR_DISABLE_SECONDS
        self._processing_error_count = 0
        with self._lock:
            self._latest_frame = None
        self.status_changed.emit("Cooling down")
        self.metrics_changed.emit("AI COOLDOWN")
        self.log_received.emit(
            f"AI temporarily paused for {AI_ERROR_DISABLE_SECONDS:.0f}s "
            "after repeated processing failures."
        )

    def _is_in_cooldown(self) -> bool:
        if self._disabled_until <= 0:
            return False

        now = time.monotonic()
        if now < self._disabled_until:
            return True

        self._disabled_until = 0.0
        self._reset_processing_errors()
        if self._ready and self._settings.enabled and not self._fatal_error:
            self.status_changed.emit("Ready")
            self.metrics_changed.emit("AI ON")
        return False

    def _reset_processing_errors(self) -> None:
        self._processing_error_count = 0
        self._last_processing_error_log = 0.0
        self._disabled_until = 0.0
