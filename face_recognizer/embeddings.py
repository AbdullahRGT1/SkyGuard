from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import threading
from typing import Any


PROVIDER_NAME = "insightface"
DEFAULT_MODEL_NAME = "buffalo_l"
MIN_DETECTION_SCORE = 0.45


@dataclass(frozen=True, slots=True)
class FaceEmbedding:
    embedding: list[float]
    bbox: tuple[int, int, int, int]
    quality: float
    face_area: float
    confidence: float
    provider: str


@dataclass(frozen=True, slots=True)
class FaceExtractionResult:
    faces: list[FaceEmbedding]
    provider: str
    raw_faces_detected: int

    @property
    def faces_detected(self) -> int:
        return len(self.faces)

    @property
    def embeddings_created(self) -> int:
        return sum(1 for face in self.faces if face.embedding)


class FaceEmbeddingExtractor:
    """InsightFace-only detector and embedding extractor.

    The previous OpenCV Haar and image-level fallback paths were intentionally removed
    because they created unstable identities and false positives. If InsightFace cannot
    detect a real face, the image contributes no face observation.
    """

    def __init__(self) -> None:
        self._app: Any | None = None
        self._init_error: str | None = None
        self._lock = threading.Lock()

    def extract(self, image_path: Path) -> list[FaceEmbedding]:
        return self.extract_with_diagnostics(image_path).faces

    def extract_with_diagnostics(self, image_path: Path) -> FaceExtractionResult:
        app = self._ensure_app()
        if app is None:
            return FaceExtractionResult([], PROVIDER_NAME, 0)

        try:
            import cv2
        except ImportError:
            self._init_error = "OpenCV is required for InsightFace image loading."
            return FaceExtractionResult([], PROVIDER_NAME, 0)

        image = cv2.imread(str(image_path))
        if image is None:
            return FaceExtractionResult([], PROVIDER_NAME, 0)

        height, width = image.shape[:2]
        raw_faces = app.get(image)
        observations: list[FaceEmbedding] = []

        for face in raw_faces:
            confidence = float(getattr(face, "det_score", 0.0) or 0.0)
            if confidence < MIN_DETECTION_SCORE:
                continue

            embedding = _embedding_from_face(face)
            if not embedding:
                continue

            bbox = _bbox_from_face(face, width, height)
            area = _area_ratio(bbox, width, height)
            quality = _quality_score(confidence, area)
            observations.append(
                FaceEmbedding(
                    embedding=embedding,
                    bbox=bbox,
                    quality=quality,
                    face_area=area,
                    confidence=confidence,
                    provider=PROVIDER_NAME,
                )
            )

        return FaceExtractionResult(
            _dedupe_observations(observations),
            PROVIDER_NAME,
            len(raw_faces),
        )

    def last_error(self) -> str | None:
        return self._init_error

    def _ensure_app(self):
        if self._app is not None:
            return self._app
        if self._init_error:
            return None

        with self._lock:
            if self._app is not None:
                return self._app
            if self._init_error:
                return None

            try:
                from insightface.app import FaceAnalysis
            except ImportError as exc:
                self._init_error = f"InsightFace is not installed: {exc}"
                return None

            providers = _onnx_providers()
            model_name = os.getenv("SKYGUARD_INSIGHTFACE_MODEL", DEFAULT_MODEL_NAME)
            try:
                app = FaceAnalysis(
                    name=model_name,
                    providers=providers,
                    allowed_modules=["detection", "recognition"],
                )
                app.prepare(ctx_id=_ctx_id(providers), det_size=(640, 640))
            except Exception as exc:
                self._init_error = f"InsightFace model initialization failed: {exc}"
                return None

            self._app = app
            return self._app


def _onnx_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError:
        return ["CPUExecutionProvider"]

    available = set(ort.get_available_providers())
    providers: list[str] = []
    if "CUDAExecutionProvider" in available:
        providers.append("CUDAExecutionProvider")
    if "CPUExecutionProvider" in available:
        providers.append("CPUExecutionProvider")
    return providers or ["CPUExecutionProvider"]


def _ctx_id(providers: list[str]) -> int:
    return 0 if providers and providers[0] == "CUDAExecutionProvider" else -1


def _embedding_from_face(face: Any) -> list[float]:
    embedding = getattr(face, "normed_embedding", None)
    if embedding is None:
        embedding = getattr(face, "embedding", None)
    if embedding is None:
        return []

    values = [float(value) for value in embedding]
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return []
    return [value / norm for value in values]


def _bbox_from_face(face: Any, width: int, height: int) -> tuple[int, int, int, int]:
    raw = getattr(face, "bbox", None)
    if raw is None or len(raw) < 4:
        return (0, 0, 0, 0)

    x1 = max(0, min(width, int(round(float(raw[0])))))
    y1 = max(0, min(height, int(round(float(raw[1])))))
    x2 = max(0, min(width, int(round(float(raw[2])))))
    y2 = max(0, min(height, int(round(float(raw[3])))))
    return (x1, y1, max(0, x2 - x1), max(0, y2 - y1))


def _area_ratio(bbox: tuple[int, int, int, int], width: int, height: int) -> float:
    _, _, w, h = bbox
    total = max(1, width * height)
    return round(max(0, w * h) / total, 6)


def _quality_score(confidence: float, area: float) -> float:
    area_score = min(1.0, max(0.0, area) * 20.0)
    return round((confidence * 0.75) + (area_score * 0.25), 4)


def _dedupe_observations(observations: list[FaceEmbedding]) -> list[FaceEmbedding]:
    deduped: list[FaceEmbedding] = []
    for observation in sorted(
        observations,
        key=lambda item: (item.confidence, item.quality, item.face_area),
        reverse=True,
    ):
        if any(_bbox_iou(observation.bbox, kept.bbox) >= 0.45 for kept in deduped):
            continue
        deduped.append(observation)
    return deduped


def _bbox_iou(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    left_x2 = lx + lw
    left_y2 = ly + lh
    right_x2 = rx + rw
    right_y2 = ry + rh

    inter_x1 = max(lx, rx)
    inter_y1 = max(ly, ry)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    union = (lw * lh) + (rw * rh) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
