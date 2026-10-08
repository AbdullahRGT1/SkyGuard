from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from face_recognizer.embeddings import cosine_similarity
from face_recognizer.store import PendingObservation


@dataclass(slots=True)
class AlertGroup:
    label: str
    violation_type: str
    observations: list[PendingObservation]
    representative: PendingObservation

    @property
    def score(self) -> float:
        severity = sum(sum(int(v) for v in item.violations.values()) for item in self.observations)
        return (
            severity * 10.0
            + len(self.observations) * 2.0
            + self.representative.quality * 5.0
            + self.representative.face_area * 10.0
            + self.representative.confidence
        )

    def summary(self) -> dict:
        first_seen = min(item.timestamp for item in self.observations)
        last_seen = max(item.timestamp for item in self.observations)
        violations: Counter[str] = Counter()
        for item in self.observations:
            for name, count in item.violations.items():
                violations[name] += int(count)
        return {
            "label": self.label,
            "violation_type": self.violation_type,
            "appearances": len(self.observations),
            "first_seen": datetime.fromtimestamp(first_seen).strftime("%H:%M:%S"),
            "last_seen": datetime.fromtimestamp(last_seen).strftime("%H:%M:%S"),
            "violations": dict(violations),
            "quality": round(self.representative.quality, 4),
            "face_area": round(self.representative.face_area, 6),
            "confidence": round(self.representative.confidence, 4),
            "image": str(self.representative.image_path),
        }


def cluster_observations(
    observations: list[PendingObservation],
    *,
    similarity_threshold: float,
    group_similar_faces: bool,
) -> list[AlertGroup]:
    clusters: list[list[PendingObservation]] = []
    centroids: list[list[float]] = []

    for observation in observations:
        if not group_similar_faces:
            clusters.append([observation])
            centroids.append(observation.embedding)
            continue

        best_index = -1
        best_similarity = -1.0
        for index, centroid in enumerate(centroids):
            if clusters[index][0].violation_type != observation.violation_type:
                continue
            similarity = cosine_similarity(observation.embedding, centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index

        if best_index >= 0 and best_similarity >= similarity_threshold:
            clusters[best_index].append(observation)
            centroids[best_index] = _average_embedding(
                [item.embedding for item in clusters[best_index]]
            )
        else:
            clusters.append([observation])
            centroids.append(observation.embedding)

    groups: list[AlertGroup] = []
    for index, cluster in enumerate(clusters, start=1):
        representative = max(
            cluster,
            key=lambda item: (
                sum(int(value) for value in item.violations.values()),
                item.quality,
                item.face_area,
                item.confidence,
            ),
        )
        groups.append(
            AlertGroup(
                label=f"Person #{index}",
                violation_type=representative.violation_type,
                observations=cluster,
                representative=representative,
            )
        )
    return groups


def select_top_groups(groups: list[AlertGroup], max_images: int) -> list[AlertGroup]:
    selected: list[AlertGroup] = []
    used_images: set[str] = set()
    for group in sorted(groups, key=lambda group: group.score, reverse=True):
        image_key = str(group.representative.image_path.resolve())
        if image_key in used_images:
            continue
        selected.append(group)
        used_images.add(image_key)
        if len(selected) >= max_images:
            break
    return selected


def _average_embedding(embeddings: list[list[float]]) -> list[float]:
    if not embeddings:
        return []
    size = len(embeddings[0])
    if size == 0:
        return []
    return [
        sum(embedding[index] for embedding in embeddings if len(embedding) == size)
        / len(embeddings)
        for index in range(size)
    ]
