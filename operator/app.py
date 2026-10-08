from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def main() -> int:
    try:
        from main_window import OperatorMainWindow
        from PySide6.QtWidgets import QApplication

        from shared.constants import APP_NAME
        from shared.ui_theme import theme_manager
    except ImportError as exc:
        print("Missing GUI dependency. Run: pip install -r requirements.txt")
        print(f"Import error: {exc}")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    theme_manager().initialize(app, "auto")
    window = OperatorMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
