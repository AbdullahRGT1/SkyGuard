from __future__ import annotations

import json
import os
from pathlib import Path

from shared.settings import OperatorSettings

APP_DIR_NAME = "SkyGuard"
LEGACY_APP_DIR_NAME = "SIMPLE_STREAM"
SETTINGS_FILE_NAME = "operator_settings.json"


class OperatorSettingsStore:
    def __init__(self) -> None:
        base_dir = Path(os.getenv("APPDATA") or Path.home())
        self.path = base_dir / APP_DIR_NAME / SETTINGS_FILE_NAME
        self.legacy_path = base_dir / LEGACY_APP_DIR_NAME / SETTINGS_FILE_NAME

    def load(self) -> OperatorSettings:
        path = self.path if self.path.exists() else self.legacy_path
        if not path.exists():
            return OperatorSettings()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return OperatorSettings.from_dict(data)
        except Exception:
            return OperatorSettings()

    def save(self, settings: OperatorSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings.to_dict(), indent=2),
            encoding="utf-8",
        )


def available_ai_models(project_root: Path) -> list[str]:
    model_dir = project_root / "AI_layer" / "yolo"
    if not model_dir.exists():
        return []

    return sorted(path.name for path in model_dir.glob("*.pt"))
