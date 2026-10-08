from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
import queue
import threading
import time

from face_recognizer.clustering import cluster_observations, select_top_groups
from face_recognizer.embeddings import FaceEmbeddingExtractor
from face_recognizer.n8n_sender import N8nSender
from face_recognizer.store import SmartAlertStore
from shared.settings import SmartAlertSettings


class SmartAlertService:
    def __init__(self, project_root: Path, log: Callable[[str], None]) -> None:
        self._project_root = project_root
        self._log = log
        self._settings = SmartAlertSettings()
        self._store = SmartAlertStore(project_root / "face_recognizer" / "smart_alerts.sqlite3")
        self._extractor = FaceEmbeddingExtractor()
        self._sender = N8nSender()
        self._queue: queue.Queue[tuple[Path, dict[str, int], str, float]] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_batch_at = time.monotonic()

    def configure(self, settings: SmartAlertSettings) -> None:
        self._settings = settings
        if settings.enabled:
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._last_batch_at = time.monotonic()
        self._worker = threading.Thread(
            target=self._run,
            name="smart-alert-service",
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
        self._worker = None

    def record_candidate(
        self,
        image_path: Path,
        class_counts: dict[str, int],
        violation_summary: str,
    ) -> None:
        if not self._settings.enabled:
            return
        self._queue.put((image_path, dict(class_counts), violation_summary, time.time()))

    def flush_now(self) -> None:
        self._process_queue()
        self._send_batch()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._process_queue()
            interval_seconds = max(60, self._settings.batch_interval_minutes * 60)
            if time.monotonic() - self._last_batch_at >= interval_seconds:
                self._send_batch()
                self._last_batch_at = time.monotonic()
            self._stop_event.wait(1.0)

    def _process_queue(self) -> None:
        while True:
            try:
                image_path, class_counts, violation_summary, timestamp = self._queue.get_nowait()
            except queue.Empty:
                return

            try:
                self._record_now(image_path, class_counts, violation_summary, timestamp)
            except Exception as exc:
                self._log(f"Smart Alerts could not index {image_path.name}: {exc}")
            finally:
                self._queue.task_done()

    def _record_now(
        self,
        image_path: Path,
        class_counts: dict[str, int],
        violation_summary: str,
        timestamp: float,
    ) -> None:
        if not image_path.exists():
            self._log(f"Smart Alerts skipped missing image: {image_path}")
            return

        violations = self._violation_counts(class_counts)
        if not violations:
            return

        extraction = self._extractor.extract_with_diagnostics(image_path)
        expected_people = self._expected_people_count(class_counts)
        faces = self._cap_faces_to_ai_count(extraction.faces, expected_people)
        observations = [
            {
                "embedding": face.embedding,
                "bbox": list(face.bbox),
                "quality": face.quality,
                "face_area": face.face_area,
                "confidence": face.confidence,
                "provider": face.provider,
            }
            for face in faces
            if face.embedding
        ]
        self._log(
            "Smart Alerts diagnostics | "
            f"Image: {image_path.name} | "
            f"Provider: {extraction.provider} | "
            f"Faces detected: {len(faces)} | "
            f"Embeddings created: {len(observations)}"
        )
        if not observations:
            if extraction.provider == "insightface" and self._extractor.last_error():
                self._log(f"Smart Alerts InsightFace error: {self._extractor.last_error()}")
            self._log(f"Smart Alerts found no usable face/image embedding in {image_path.name}.")
            return

        event_id = self._store.add_event(
            image_path=image_path,
            timestamp=timestamp,
            violation_summary=violation_summary,
            violations=violations,
            observations=observations,
        )
        self._log(
            f"Smart Alerts indexed event #{event_id}: "
            f"{len(observations)} face record(s), {', '.join(violations)}."
        )

    def _send_batch(self) -> None:
        settings = self._settings
        if not settings.enabled:
            return
        if not settings.webhook_url:
            return

        all_observations = [
            observation
            for observation in self._store.pending_observations()
            if observation.image_path.exists()
        ]
        if not all_observations:
            return

        observations, ignored_fallback_count = self._groupable_observations(all_observations)
        if not observations:
            return

        groups = cluster_observations(
            observations,
            similarity_threshold=self._effective_similarity(settings.face_similarity, observations),
            group_similar_faces=settings.group_similar_faces,
        )
        self._log(
            "Smart Alerts batch diagnostics | "
            f"Pending observations: {len(all_observations)} | "
            f"Grouped observations: {len(observations)} | "
            f"Ignored fallback: {ignored_fallback_count} | "
            f"Groups matched: {len(groups)}"
        )
        selected = select_top_groups(groups, settings.max_images_per_batch)
        selected = self._limit_weak_identity_duplicates(selected)
        self._log(
            "Smart Alerts selection diagnostics | "
            f"Selected after identity filter: {len(selected)}"
        )
        if not selected:
            return

        processed_event_ids = [observation.event_id for observation in all_observations]
        image_paths = [group.representative.image_path for group in selected]
        selected_violation_totals: Counter[str] = Counter()
        violation_appearances: Counter[str] = Counter()
        for group in selected:
            for name, count in group.representative.violations.items():
                selected_violation_totals[name] += int(count)
        for observation in all_observations:
            for name, count in observation.violations.items():
                violation_appearances[name] += int(count)

        payload = {
            "source": "SkyGuard Operator",
            "window_minutes": settings.batch_interval_minutes,
            "total_candidates": len({item.event_id for item in all_observations}),
            "total_observations": len(all_observations),
            "grouped_observations": len(observations),
            "ignored_fallback_observations": ignored_fallback_count,
            "unique_groups": len(groups),
            "selected_images": len(selected),
            "violations": dict(selected_violation_totals),
            "violation_appearances": dict(violation_appearances),
            "people": [group.summary() for group in selected],
        }
        if settings.send_summary:
            payload["summary_text"] = self._summary_text(payload)

        try:
            self._sender.send(settings.webhook_url, payload, image_paths)
        except Exception as exc:
            self._log(f"Smart Alerts webhook send failed: {exc}")
            return

        self._store.mark_events_sent(processed_event_ids)
        if settings.delete_temp_images:
            self._store.prune_sent_records()
        self._log(
            f"Smart Alerts sent {len(selected)} image(s) from "
            f"{len(all_observations)} pending face observation(s)."
        )

    @staticmethod
    def _violation_counts(class_counts: dict[str, int]) -> dict[str, int]:
        result: dict[str, int] = {}
        for name, count in class_counts.items():
            if not str(name).startswith("NO-"):
                continue
            normalized = str(name).replace("-", "_").replace(" ", "_").upper()
            result[normalized] = int(count)
        return result

    @staticmethod
    def _expected_people_count(class_counts: dict[str, int]) -> int:
        total = 0
        for name, count in class_counts.items():
            normalized = str(name).replace("-", "_").replace(" ", "_").upper()
            if normalized in {"MASK", "NO_MASK"}:
                total += int(count)
        return total

    @staticmethod
    def _cap_faces_to_ai_count(faces: list, expected_people: int) -> list:
        if expected_people <= 0 or len(faces) <= expected_people:
            return faces
        return sorted(
            faces,
            key=lambda face: (face.quality, face.face_area, face.confidence),
            reverse=True,
        )[:expected_people]

    @staticmethod
    def _groupable_observations(observations: list) -> tuple[list, int]:
        real_observations = [
            observation
            for observation in observations
            if observation.provider != "image-fallback"
        ]
        if real_observations:
            return real_observations, len(observations) - len(real_observations)

        if not observations:
            return [], 0

        best_fallback = max(
            observations,
            key=lambda observation: (
                sum(int(value) for value in observation.violations.values()),
                observation.quality,
                observation.confidence,
            ),
        )
        return [best_fallback], len(observations) - 1

    @staticmethod
    def _limit_weak_identity_duplicates(groups: list) -> list:
        strong_providers = {"insightface", "face_recognition"}
        if any(group.representative.provider in strong_providers for group in groups):
            return groups

        selected_by_violation: dict[str, object] = {}
        for group in sorted(groups, key=lambda item: item.score, reverse=True):
            key = group.violation_type
            if key in selected_by_violation:
                continue
            selected_by_violation[key] = group
        return list(selected_by_violation.values())

    @staticmethod
    def _effective_similarity(configured_similarity: float, observations: list) -> float:
        if observations and all(
            observation.provider == "insightface" for observation in observations
        ):
            return min(configured_similarity, 0.45)
        return configured_similarity

    @staticmethod
    def _summary_text(payload: dict) -> str:
        lines = [
            "SkyGuard Alert - last "
            f"{payload.get('window_minutes')} minute(s)",
            f"Candidates: {payload.get('total_candidates')}",
            f"Unique groups: {payload.get('unique_groups')}",
            f"Selected images: {payload.get('selected_images')}",
        ]
        for person in payload.get("people", []):
            violations = ", ".join(
                f"{key}: {value}" for key, value in person.get("violations", {}).items()
            )
            lines.append(
                f"{person.get('label')} | {person.get('violation_type')} | "
                f"Appearances: {person.get('appearances')} | "
                f"{person.get('first_seen')} - {person.get('last_seen')} | "
                f"{violations}"
            )
        return "\n".join(lines)
