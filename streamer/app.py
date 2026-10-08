from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from shared.constants import APP_NAME
        from shared.ui_theme import theme_manager
        from streamer.main_window import StreamerMainWindow
    except ImportError as exc:
        print("Missing GUI dependency. Run: pip install -r requirements.txt")
        print(f"Import error: {exc}")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    theme_manager().initialize(app, "auto")
    window = StreamerMainWindow()
    window.show()
    return app.exec()
