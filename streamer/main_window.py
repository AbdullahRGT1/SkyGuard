from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentWindow, SubtitleLabel
from qfluentwidgets import FluentIcon as FIF

from shared.config import StreamerConfig
from shared.constants import DEFAULT_DEV_PIN
from shared.network import local_access_hint
from shared.state import StreamerState
from shared.ui_theme import theme_manager
from shared.ui_widgets import AcrylicGlowFrame, ThemedStatusBadge
from streamer.control_server import StreamerControlServer
from streamer.services.stream_service import StreamService
from streamer.state_machine import StreamerStateMachine


class StreamerUiBridge(QObject):
    log_received = Signal(str)
    state_changed = Signal(str)


StatusBadge = ThemedStatusBadge


class StreamerMainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("streamerWindow")
        self.setWindowTitle("SkyGuard - Streamer")
        self.resize(980, 640)

        self._closing = False
        self._bridge = StreamerUiBridge()
        self._bridge.log_received.connect(self._append_log)
        self._bridge.state_changed.connect(self._set_state)

        self._config = StreamerConfig.from_env()
        self._state_machine = StreamerStateMachine()
        self._state_machine.add_listener(self._on_state_changed)
        self._stream_service = StreamService(log=self._emit_log)
        self._control_server = StreamerControlServer(
            config=self._config,
            state_machine=self._state_machine,
            stream_service=self._stream_service,
            log=self._emit_log,
        )

        self._build_views()
        theme_manager().register(self)
        self._control_server.start_background()
        self._append_log("Streamer app launched. Waiting for authenticated START_STREAM.")
        if os.getenv("SKYGUARD_PIN"):
            self._append_log("PIN loaded from SKYGUARD_PIN.")
        elif os.getenv("SIMPLE_STREAM_PIN"):
            self._append_log("PIN loaded from legacy SIMPLE_STREAM_PIN.")
        else:
            self._append_log(f"Development PIN active: {DEFAULT_DEV_PIN}.")

    def _build_views(self) -> None:
        tokens = theme_manager().tokens()

        # ── Status view ──────────────────────────────────────────
        self.status_view = QWidget()
        self.status_view.setObjectName("statusContent")
        theme_manager().register(self.status_view)
        status_layout = QVBoxLayout(self.status_view)
        status_layout.setContentsMargins(40, 36, 40, 36)
        status_layout.setSpacing(24)

        # Hero panel
        hero = AcrylicGlowFrame(variant="strong")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(12)

        title = SubtitleLabel("SkyGuard Streamer")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = BodyLabel("Ready and private until an authenticated operator starts video")
        subtitle.setStyleSheet(f"color: {tokens.text_secondary}; font-size: 13px;")

        self.state_badge = StatusBadge(StreamerState.BOOTING.value, "waiting")
        self.server_label = BodyLabel(
            f"Listening: {self._config.control_host}:{self._config.control_port}    "
            f"Video: UDP {self._config.video_port}"
        )
        self.access_label = BodyLabel(
            f"Connect operator to: {local_access_hint(self._config.control_port)}"
        )

        hero_status_row = QHBoxLayout()
        hero_status_row.setSpacing(12)
        state_label = BodyLabel("State")
        state_label.setStyleSheet(f"color: {tokens.text_secondary}; font-size: 12px;")
        hero_status_row.addWidget(state_label)
        hero_status_row.addWidget(self.state_badge)
        hero_status_row.addStretch(1)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addLayout(hero_status_row)

        # Network info panel
        panel = AcrylicGlowFrame()
        panel.setObjectName("statusPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 22, 24, 22)
        panel_layout.setSpacing(16)
        panel_layout.addWidget(self.server_label)
        panel_layout.addWidget(self.access_label)

        status_layout.addWidget(hero)
        status_layout.addWidget(panel)
        status_layout.addStretch(1)

        # ── Logs view ────────────────────────────────────────────
        self.logs_view = QWidget()
        self.logs_view.setObjectName("logsContent")
        theme_manager().register(self.logs_view)
        logs_layout = QVBoxLayout(self.logs_view)
        logs_layout.setContentsMargins(40, 36, 40, 36)
        logs_layout.setSpacing(16)

        logs_title = SubtitleLabel("Logs")
        logs_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        logs_layout.addWidget(logs_title)

        logs_card = AcrylicGlowFrame()
        logs_card_layout = QVBoxLayout(logs_card)
        logs_card_layout.setContentsMargins(20, 20, 20, 20)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(700)
        logs_card_layout.addWidget(self.log_text, 1)
        logs_layout.addWidget(logs_card, 1)

        # ── Navigation ───────────────────────────────────────────
        self.addSubInterface(self.status_view, FIF.HOME, "Status")
        self.addSubInterface(self.logs_view, FIF.DOCUMENT, "Logs")

    # ── state handling ───────────────────────────────────────────

    def _emit_log(self, message: str) -> None:
        if self._closing:
            return
        self._bridge.log_received.emit(message)

    def _on_state_changed(self, state: StreamerState, reason: str | None) -> None:
        if self._closing:
            return
        message = f"State changed to {state.value}."
        if reason:
            message = f"{message} Reason: {reason}"
        self._bridge.state_changed.emit(state.value)
        self._emit_log(message)

    def _set_state(self, state: str) -> None:
        if state == StreamerState.STREAMING.value:
            role = "success"
        elif state in {StreamerState.ERROR.value, StreamerState.STOPPING.value}:
            role = "error"
        else:
            role = "waiting"
        self.state_badge.set_state(state, role)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{timestamp}] {message}")

    # ── theme ────────────────────────────────────────────────────

    def apply_theme(self, _tokens) -> None:
        self.update()

    # ── lifecycle ────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        self._control_server.stop_background()
        super().closeEvent(event)
