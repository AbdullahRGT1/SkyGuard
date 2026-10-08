from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic

from ai_processor import AiProcessor
from control_client import OperatorControlClient
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentWindow,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    SubtitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)
from settings_panel import SettingsPanel
from settings_store import OperatorSettingsStore
from video_receiver import VideoReceiver
from violation_capture import ViolationCaptureManager
from face_recognizer import SmartAlertService

from shared.config import OperatorConfig
from shared.network import parse_control_endpoint
from shared.settings import OperatorSettings, VideoSettings
from shared.state import StreamerState
from shared.ui_theme import theme_manager
from shared.ui_widgets import AcrylicGlowFrame, ThemedStatusBadge

PREVIEW_RENDER_INTERVAL_MS = 16
AI_METRICS_REFRESH_SECONDS = 0.25
LOG_FLUSH_INTERVAL_MS = 100


class OperatorUiBridge(QObject):
    log_received = Signal(str)
    streamer_state_changed = Signal(str)
    connection_state_changed = Signal(str)
    stream_info_changed = Signal(object)


StatusBadge = ThemedStatusBadge


class AspectRatioPreviewLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._image: QImage | None = None

    def set_frame(self, image: QImage) -> None:
        self._image = QImage(image)
        self.setText("")
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None and not self._image.isNull()

    def clear(self) -> None:
        self._image = None
        super().clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.has_frame():
            super().paintEvent(event)
            return

        super().paintEvent(event)
        image = self._image
        if image is None:
            return

        frame_size = image.size()
        target_area = self.contentsRect().adjusted(2, 2, -2, -2)
        if target_area.isEmpty():
            return

        scaled_size = frame_size.scaled(
            target_area.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        x = target_area.x() + (target_area.width() - scaled_size.width()) // 2
        y = target_area.y() + (target_area.height() - scaled_size.height()) // 2
        target_rect = QRect(x, y, scaled_size.width(), scaled_size.height())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(target_rect, image)


class FullscreenPreviewWindow(QWidget):
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("previewFullscreenWindow")
        self.setWindowTitle("SkyGuard - Preview Full Screen")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.title_label = SubtitleLabel("Stream Preview")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.stream_info_badge = StatusBadge("No stream", "offline")
        self.preview_mode_badge = StatusBadge("RAW", "offline")
        self.ai_status_badge = StatusBadge("AI Disabled", "offline")
        self.violation_badge = StatusBadge("Alerts 0", "offline")
        self.close_button = PushButton("Exit")
        self.close_button.setIcon(FIF.BACK_TO_WINDOW)
        self.close_button.setToolTip("Exit full screen")
        self.close_button.clicked.connect(self.close)

        toolbar.addWidget(self.title_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.stream_info_badge)
        toolbar.addWidget(self.preview_mode_badge)
        toolbar.addWidget(self.ai_status_badge)
        toolbar.addWidget(self.violation_badge)
        toolbar.addWidget(self.close_button)
        layout.addLayout(toolbar)

        self.preview_label = AspectRatioPreviewLabel("NO SIGNAL")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.preview_label.setScaledContents(False)
        self.preview_label.setStyleSheet(theme_manager().preview_stylesheet())
        layout.addWidget(self.preview_label, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self.close)
        theme_manager().register(self)

    def set_frame(self, image: QImage) -> None:
        self.preview_label.set_frame(image)

    def set_placeholder(self, text: str) -> None:
        self.preview_label.clear()
        self.preview_label.setText(text)

    def set_statuses(
        self,
        *,
        stream_info: tuple[str, str],
        preview_mode: tuple[str, str],
        ai_status: tuple[str, str],
        violations: tuple[str, str],
    ) -> None:
        self.stream_info_badge.set_state(stream_info[0], stream_info[1])
        self.preview_mode_badge.set_state(preview_mode[0], preview_mode[1])
        self.ai_status_badge.set_state(ai_status[0], ai_status[1])
        self.violation_badge.set_state(violations[0], violations[1])

    def apply_theme(self, _tokens) -> None:
        self.setStyleSheet(f"background: {theme_manager().tokens().background};")
        self.preview_label.setStyleSheet(theme_manager().preview_stylesheet())

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


class OperatorMainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("operatorWindow")
        self.setWindowTitle("SkyGuard - Operator")
        self.resize(1040, 620)
        self.setMinimumSize(820, 520)

        self._project_root = Path(__file__).resolve().parents[1]
        self._config = OperatorConfig.from_env()
        self._settings_store = OperatorSettingsStore()
        self._settings = self._settings_store.load()
        self._violation_capture = ViolationCaptureManager(self._project_root / "Images")
        self._violation_capture.configure(self._settings.violation_capture)
        self._smart_alert_service = SmartAlertService(
            self._project_root,
            log=self._bridge_log,
        )
        self._smart_alert_service.configure(self._settings.smart_alerts)
        self._client: OperatorControlClient | None = None
        self._last_frame: QImage | None = None
        self._pending_preview_frame: QImage | None = None
        self._last_ai_metrics = ""
        self._last_ai_metrics_at = 0.0
        self._connection_state = "DISCONNECTED"
        self._streamer_state = "UNKNOWN"
        self._stream_video_port = self._config.video_port
        self._stream_video_settings = self._settings.video
        self._preview_mode_state = ("RAW", "offline")
        self._ai_status_state = ("AI Disabled", "offline")
        self._violation_state = ("Alerts 0", "offline")
        self._stream_info_state = ("No stream", "offline")
        self._current_ai_status = "Disabled"
        self._fullscreen_preview: FullscreenPreviewWindow | None = None
        self._restart_after_ready = False
        self._pending_log_lines: list[str] = []
        self._preview_render_timer = QTimer(self)
        self._preview_render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._preview_render_timer.setInterval(PREVIEW_RENDER_INTERVAL_MS)
        self._preview_render_timer.timeout.connect(self._flush_preview_frame)
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setInterval(LOG_FLUSH_INTERVAL_MS)
        self._log_flush_timer.timeout.connect(self._flush_log_lines)
        self._bridge = OperatorUiBridge()
        self._bridge.log_received.connect(self._append_log)
        self._bridge.streamer_state_changed.connect(self._set_streamer_state)
        self._bridge.connection_state_changed.connect(self._set_connection_state)
        self._bridge.stream_info_changed.connect(self._set_stream_info)
        self._video_receiver = VideoReceiver(log=self._bridge.log_received.emit)
        self._video_receiver.frame_received.connect(self._handle_received_frame)
        self._video_receiver.status_changed.connect(self._set_video_status)
        self._ai_processor = AiProcessor(project_root=self._project_root)
        self._ai_processor.frame_processed.connect(self._display_frame)
        self._ai_processor.detection_processed.connect(self._handle_ai_detection)
        self._ai_processor.status_changed.connect(self._set_ai_status)
        self._ai_processor.metrics_changed.connect(self._set_ai_metrics)
        self._ai_processor.violations_changed.connect(self._set_violation_count)
        self._ai_processor.log_received.connect(self._bridge.log_received.emit)
        self._ai_processor.set_detection_events_enabled(
            self._settings.violation_capture.enabled
        )

        self._build_views()
        self._update_stream_info_badge()
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self._toggle_fullscreen_preview)
        theme_manager().register(self)
        self._ai_processor.configure(self._settings.ai)
        self._append_log("Operator app launched.")

    def _bridge_log(self, message: str) -> None:
        if hasattr(self, "_bridge"):
            self._bridge.log_received.emit(message)

    # ── views ────────────────────────────────────────────────────

    def _build_views(self) -> None:
        tokens = theme_manager().tokens()

        # ── Dashboard ────────────────────────────────────────────
        dashboard_content = QWidget()
        dashboard_content.setObjectName("dashboardContent")
        theme_manager().register(dashboard_content)
        dashboard = QVBoxLayout(dashboard_content)
        dashboard.setContentsMargins(40, 36, 40, 36)
        dashboard.setSpacing(24)

        # Hero panel
        hero_panel = AcrylicGlowFrame(variant="strong")
        hero_panel.setObjectName("operatorHeroPanel")
        grid = QGridLayout(hero_panel)
        grid.setContentsMargins(24, 22, 24, 22)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        title = SubtitleLabel("SkyGuard Operator")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = BodyLabel("Live control · Safety detection · Low-latency preview")
        subtitle.setStyleSheet(f"color: {tokens.text_secondary}; font-size: 13px;")
        self.connection_badge = StatusBadge("DISCONNECTED", "offline")
        self.streamer_badge = StatusBadge("UNKNOWN", "offline")
        grid.addWidget(title, 0, 0, 1, 2)
        grid.addWidget(subtitle, 1, 0, 1, 2)

        badge_labels_style = f"color: {tokens.text_secondary}; font-size: 12px;"
        ctrl_label = BodyLabel("Control")
        ctrl_label.setStyleSheet(badge_labels_style)
        strm_label = BodyLabel("Streamer")
        strm_label.setStyleSheet(badge_labels_style)
        grid.addWidget(ctrl_label, 0, 3)
        grid.addWidget(self.connection_badge, 0, 4)
        grid.addWidget(strm_label, 1, 3)
        grid.addWidget(self.streamer_badge, 1, 4)
        grid.setColumnStretch(2, 1)
        dashboard.addWidget(hero_panel)

        # Command panel
        command_panel = AcrylicGlowFrame()
        command_panel.setObjectName("commandPanel")
        command_layout = QGridLayout(command_panel)
        command_layout.setContentsMargins(24, 22, 24, 22)
        command_layout.setHorizontalSpacing(16)
        command_layout.setVerticalSpacing(16)

        self.host_input = LineEdit()
        self.host_input.setText(self._config.default_host)
        self.host_input.setPlaceholderText("Streamer IP, IP:port, or ws://IP:port")

        self.pin_input = PasswordLineEdit()
        self.pin_input.setMaxLength(4)
        self.pin_input.setPlaceholderText("PIN")

        self.connect_button = PrimaryPushButton("Connect")
        self.disconnect_button = PushButton("Disconnect")
        self.start_button = PrimaryPushButton("Start Stream")
        self.stop_button = PushButton("Stop Stream")

        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(self._disconnect)
        self.start_button.clicked.connect(self._start_stream)
        self.stop_button.clicked.connect(self._stop_stream)

        command_layout.addWidget(BodyLabel("Address"), 0, 0)
        command_layout.addWidget(self.host_input, 0, 1)
        command_layout.addWidget(BodyLabel("PIN"), 0, 2)
        command_layout.addWidget(self.pin_input, 0, 3)
        command_layout.addWidget(self.connect_button, 0, 4)
        command_layout.addWidget(self.disconnect_button, 0, 5)
        command_layout.addWidget(self.start_button, 1, 4)
        command_layout.addWidget(self.stop_button, 1, 5)
        command_layout.setColumnStretch(1, 1)

        dashboard.addWidget(command_panel)
        dashboard.addStretch(1)
        self.dashboard_view = self._scrollable_view(dashboard_content, "dashboardScroll")

        # ── Preview ──────────────────────────────────────────────
        preview_content = QWidget()
        preview_content.setObjectName("previewContent")
        theme_manager().register(preview_content)
        preview_layout = QVBoxLayout(preview_content)
        preview_layout.setContentsMargins(40, 36, 40, 36)
        preview_layout.setSpacing(16)

        preview_header = QHBoxLayout()
        preview_header.setSpacing(12)
        preview_title = SubtitleLabel("Stream Preview")
        preview_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.stream_info_badge = StatusBadge("No stream", "offline")
        self.fullscreen_button = PushButton("Full Screen")
        self.fullscreen_button.setIcon(FIF.FULL_SCREEN)
        self.fullscreen_button.setToolTip("Open preview in full screen")
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen_preview)
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        preview_header.addWidget(self.stream_info_badge)
        preview_header.addWidget(self.fullscreen_button)
        preview_layout.addLayout(preview_header)

        preview_card = AcrylicGlowFrame(variant="strong")
        preview_card_layout = QVBoxLayout(preview_card)
        preview_card_layout.setContentsMargins(18, 18, 18, 18)
        preview_card_layout.setSpacing(12)

        preview_status_row = QHBoxLayout()
        preview_status_row.setSpacing(10)
        self.preview_mode_badge = StatusBadge("RAW", "offline")
        self.ai_status_badge = StatusBadge("AI Disabled", "offline")
        self.violation_badge = StatusBadge("Alerts 0", "offline")
        preview_status_row.addWidget(self.preview_mode_badge)
        preview_status_row.addWidget(self.ai_status_badge)
        preview_status_row.addWidget(self.violation_badge)
        preview_status_row.addStretch(1)
        preview_card_layout.addLayout(preview_status_row)

        self.preview_label = AspectRatioPreviewLabel("NO SIGNAL")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(460)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.preview_label.setScaledContents(False)
        self.preview_label.setStyleSheet(theme_manager().preview_stylesheet())
        self.preview_label.installEventFilter(self)
        preview_card_layout.addWidget(self.preview_label, 1)
        preview_layout.addWidget(preview_card, 1)
        self.preview_view = self._scrollable_view(preview_content, "previewScroll")

        # ── Logs ─────────────────────────────────────────────────
        logs_content = QWidget()
        logs_content.setObjectName("logsContent")
        theme_manager().register(logs_content)
        logs_layout = QVBoxLayout(logs_content)
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
        self.logs_view = self._scrollable_view(logs_content, "logsScroll")

        # ── Settings ─────────────────────────────────────────────
        self.settings_view: SettingsPanel | None = None
        self.settings_scroll = self._scrollable_view(
            self._settings_placeholder(),
            "settingsScroll",
        )

        # ── Navigation ───────────────────────────────────────────
        self.addSubInterface(self.dashboard_view, FIF.HOME, "Dashboard")
        self.addSubInterface(self.preview_view, FIF.VIDEO, "Preview")
        self.addSubInterface(self.logs_view, FIF.DOCUMENT, "Logs")
        self.addSubInterface(self.settings_scroll, FIF.SETTING, "Settings")

    @staticmethod
    def _scrollable_view(content: QWidget, object_name: str) -> SmoothScrollArea:
        scroll_area = SmoothScrollArea()
        scroll_area.setObjectName(object_name)
        content.setMinimumWidth(720)
        scroll_area.setWidget(content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet(theme_manager().scroll_area_stylesheet())
        scroll_area.setScrollAnimation(
            Qt.Orientation.Vertical,
            140,
            QEasingCurve.Type.OutCubic,
        )
        scroll_area.setScrollAnimation(
            Qt.Orientation.Horizontal,
            140,
            QEasingCurve.Type.OutCubic,
        )
        scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StaticContents, True)
        return scroll_area

    def _settings_placeholder(self) -> QWidget:
        content = QWidget()
        content.setObjectName("settingsView")
        theme_manager().register(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(24)

        panel = AcrylicGlowFrame()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 22, 24, 22)
        panel_layout.setSpacing(10)
        title = SubtitleLabel("Settings")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = BodyLabel("Loading settings...")
        subtitle.setStyleSheet(
            f"color: {theme_manager().tokens().text_secondary}; font-size: 13px;"
        )
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)
        layout.addWidget(panel)
        layout.addStretch(1)
        return content

    def _ensure_settings_view(self) -> None:
        if self.settings_view is not None:
            return

        self.settings_scroll.setUpdatesEnabled(False)
        old_content = self.settings_scroll.takeWidget()
        try:
            settings_view = SettingsPanel(
                self._project_root,
                self._settings,
                auto_refresh_environment=False,
            )
            settings_view.settings_applied.connect(self._apply_settings)
            settings_view.set_ai_status(self._current_ai_status)
            settings_view.setMinimumWidth(720)
            self.settings_view = settings_view
            self.settings_scroll.setWidget(settings_view)
        finally:
            self.settings_scroll.setUpdatesEnabled(True)
            if old_content is not None:
                old_content.deleteLater()

    def switchTo(self, interface: QWidget):  # noqa: N802
        if interface is getattr(self, "settings_scroll", None):
            self._ensure_settings_view()
        return super().switchTo(interface)

    # ── control actions ──────────────────────────────────────────

    def _connect(self) -> None:
        address = self.host_input.text().strip()
        pin = self.pin_input.text().strip()
        if not address or len(pin) != 4 or not pin.isdigit():
            self._append_log("Enter the streamer address and a 4-digit PIN.")
            return

        try:
            endpoint = parse_control_endpoint(address, self._config.control_port)
        except ValueError as exc:
            self._append_log(str(exc))
            return

        if self._client:
            self._client.disconnect()

        self._client = OperatorControlClient(
            log=self._bridge.log_received.emit,
            state_changed=self._bridge.streamer_state_changed.emit,
            connection_changed=self._bridge.connection_state_changed.emit,
            stream_info_changed=self._bridge.stream_info_changed.emit,
        )
        self._client.connect_background(endpoint, pin)

    def _disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None

    def _start_stream(self) -> None:
        if not self._client:
            self._append_log("Connect to the streamer before sending START_STREAM.")
            return
        self._violation_capture.reset()
        self._stream_video_port = self._config.video_port
        self._stream_video_settings = self._settings.video
        self.preview_label.setText("STARTING")
        self._update_stream_info_badge(role_override="waiting")
        self._client.send_start_stream(self._config.video_port, self._settings.video)

    def _stop_stream(self) -> None:
        if not self._client:
            self._append_log("Connect to the streamer before sending STOP_STREAM.")
            return
        self._client.send_stop_stream()
        self._video_receiver.stop()

    # ── state handlers ───────────────────────────────────────────

    def _set_connection_state(self, state: str) -> None:
        self._connection_state = state
        role = {
            "AUTHENTICATED": "success",
            "CONNECTING": "waiting",
            "ERROR": "error",
            "DISCONNECTED": "offline",
        }.get(state, "offline")
        self.connection_badge.set_state(state, role)

    def _set_stream_info(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        try:
            self._stream_video_port = int(payload.get("video_port") or self._config.video_port)
        except (TypeError, ValueError):
            self._stream_video_port = self._config.video_port

        video_settings = payload.get("video_settings")
        if isinstance(video_settings, dict):
            try:
                self._stream_video_settings = VideoSettings.from_dict(video_settings)
            except ValueError as exc:
                self._append_log(f"Streamer returned invalid video settings: {exc}")
                self._stream_video_settings = self._settings.video
        self._update_stream_info_badge()

    def _set_streamer_state(self, state: str) -> None:
        self._streamer_state = state
        role = "waiting"
        if state == StreamerState.STREAMING.value:
            role = "success"
            self._start_video_receiver()
            if not self.preview_label.has_frame():
                self.preview_label.setText("WAITING FOR VIDEO")
        elif state == StreamerState.READY_WAITING.value:
            self._video_receiver.stop()
            self.preview_label.clear()
            self.preview_label.setText("NO SIGNAL")
            if self._restart_after_ready:
                self._restart_after_ready = False
                self._append_log("Restarting stream with updated settings.")
                self._start_stream()
        elif state == StreamerState.ERROR.value:
            role = "error"
            self._video_receiver.stop()
            self.preview_label.clear()
            self.preview_label.setText("ERROR")
            self._restart_after_ready = False
        self.streamer_badge.set_state(state, role)
        self._update_stream_info_badge()

    def _start_video_receiver(self) -> None:
        if self._video_receiver.running:
            return

        codec = self._stream_video_settings.codec
        self._video_receiver.start(self._stream_video_port, codec)

    def _set_video_status(self, status: str) -> None:
        if status == "WAITING_FOR_VIDEO":
            self._last_frame = None
            self._pending_preview_frame = None
            self.preview_label.clear()
            self.preview_label.setText("WAITING FOR VIDEO")
            self._set_fullscreen_placeholder("WAITING FOR VIDEO")
        elif status == "NO_SIGNAL":
            self._last_frame = None
            self._pending_preview_frame = None
            self.preview_label.clear()
            self.preview_label.setText("NO SIGNAL")
            self._set_fullscreen_placeholder("NO SIGNAL")
        elif status == "VIDEO_ERROR":
            self._last_frame = None
            self._pending_preview_frame = None
            self.preview_label.clear()
            self.preview_label.setText("VIDEO ERROR")
            self._set_fullscreen_placeholder("VIDEO ERROR")

    # ── frame pipeline ───────────────────────────────────────────

    def _handle_received_frame(self, image: QImage) -> None:
        if self._settings.ai.enabled and self._ai_processor.submit_frame(image):
            return

        self._display_frame(image)
        self._set_ai_metrics("RAW")
        self._set_violation_count(0)

    def _display_frame(self, image: QImage) -> None:
        self._last_frame = image
        self._pending_preview_frame = image
        fullscreen_visible = bool(
            self._fullscreen_preview and self._fullscreen_preview.isVisible()
        )
        if self.preview_label.isVisible() or fullscreen_visible:
            if not self._preview_render_timer.isActive():
                self._preview_render_timer.start()

    def _handle_ai_detection(
        self,
        raw_image: QImage,
        class_counts: object,
        _violation_count: int,
        violation_summary: str,
    ) -> None:
        counts = dict(class_counts) if isinstance(class_counts, dict) else {}
        try:
            saved_path = self._violation_capture.consider(
                raw_image,
                counts,
                violation_summary,
            )
        except Exception as exc:
            self._append_log(f"Violation image capture failed: {exc}")
            return

        if saved_path:
            self._append_log(f"Violation RAW image saved: {saved_path}")
            self._smart_alert_service.record_candidate(
                saved_path,
                counts,
                violation_summary,
            )

    # ── AI status ────────────────────────────────────────────────

    def _set_ai_status(self, status: str) -> None:
        self._current_ai_status = status
        if self.settings_view is not None:
            self.settings_view.set_ai_status(status)
        role = {
            "Disabled": "offline",
            "Loading": "waiting",
            "Ready": "success",
            "Cooling down": "waiting",
            "Missing dependencies": "error",
            "Model error": "error",
        }.get(status, "offline")
        self._ai_status_state = (f"AI {status}", role)
        self.ai_status_badge.set_state(*self._ai_status_state)
        self._sync_fullscreen_status()

    def _set_ai_metrics(self, metrics: str) -> None:
        now = monotonic()
        if metrics == self._last_ai_metrics:
            return
        if (
            metrics.startswith("AI ON")
            and now - self._last_ai_metrics_at < AI_METRICS_REFRESH_SECONDS
        ):
            return

        self._last_ai_metrics = metrics
        self._last_ai_metrics_at = now
        role = "success" if metrics.startswith("AI ON") else "offline"
        if "ERROR" in metrics:
            role = "error"
        self._preview_mode_state = (metrics, role)
        self.preview_mode_badge.set_state(*self._preview_mode_state)
        self._sync_fullscreen_status()

    def _set_violation_count(self, count: int) -> None:
        role = "error" if count else "offline"
        self._violation_state = (f"Alerts {count}", role)
        self.violation_badge.set_state(*self._violation_state)
        self._sync_fullscreen_status()

    # ── settings ─────────────────────────────────────────────────

    def _apply_settings(self, settings: OperatorSettings) -> None:
        self._settings = settings
        self._settings_store.save(settings)
        self._violation_capture.configure(settings.violation_capture)
        self._smart_alert_service.configure(settings.smart_alerts)
        self._ai_processor.set_detection_events_enabled(settings.violation_capture.enabled)
        self._ai_processor.configure(settings.ai)
        self._append_log("Settings saved.")

        if self._streamer_state == StreamerState.STREAMING.value:
            self._append_log("Applying settings by restarting the stream.")
            self._restart_after_ready = True
            self._stop_stream()

    # ── rendering ────────────────────────────────────────────────

    def _flush_preview_frame(self) -> None:
        self._render_preview_frame()
        if self._pending_preview_frame is None:
            self._preview_render_timer.stop()

    def _render_preview_frame(self, *, force: bool = False) -> None:
        image = self._pending_preview_frame
        if image is None and force:
            image = self._last_frame
        if image is None:
            return
        fullscreen_visible = bool(
            self._fullscreen_preview and self._fullscreen_preview.isVisible()
        )
        if self.preview_label.size().isEmpty() and not fullscreen_visible:
            return

        self._pending_preview_frame = None
        if not self.preview_label.size().isEmpty():
            self.preview_label.set_frame(image)
        if fullscreen_visible and self._fullscreen_preview:
            self._fullscreen_preview.set_frame(image)

    # ── log ──────────────────────────────────────────────────────

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._pending_log_lines.append(f"[{timestamp}] {message}")
        if not self._log_flush_timer.isActive():
            self._log_flush_timer.start()

    def _flush_log_lines(self) -> None:
        if not self._pending_log_lines:
            self._log_flush_timer.stop()
            return

        lines = "\n".join(self._pending_log_lines)
        self._pending_log_lines.clear()
        self.log_text.appendPlainText(lines)
        self._log_flush_timer.stop()

    # ── theme ────────────────────────────────────────────────────

    def apply_theme(self, _tokens) -> None:
        if hasattr(self, "preview_label"):
            self.preview_label.setStyleSheet(theme_manager().preview_stylesheet())
        if self._fullscreen_preview:
            self._fullscreen_preview.apply_theme(theme_manager().tokens())
        for scroll_area in self.findChildren(SmoothScrollArea):
            scroll_area.setStyleSheet(theme_manager().scroll_area_stylesheet())

    def _toggle_fullscreen_preview(self) -> None:
        if self._fullscreen_preview and self._fullscreen_preview.isVisible():
            self._fullscreen_preview.close()
            return

        fullscreen = FullscreenPreviewWindow()
        fullscreen.closed.connect(self._on_fullscreen_closed)
        self._fullscreen_preview = fullscreen
        self._sync_fullscreen_status()
        if self._last_frame is not None and not self._last_frame.isNull():
            fullscreen.set_frame(self._last_frame)
        else:
            fullscreen.set_placeholder(self.preview_label.text() or "NO SIGNAL")
        fullscreen.showFullScreen()
        fullscreen.raise_()
        fullscreen.activateWindow()

    def _on_fullscreen_closed(self) -> None:
        self._fullscreen_preview = None

    def _sync_fullscreen_status(self) -> None:
        if not self._fullscreen_preview:
            return
        self._fullscreen_preview.set_statuses(
            stream_info=self._stream_info_state,
            preview_mode=self._preview_mode_state,
            ai_status=self._ai_status_state,
            violations=self._violation_state,
        )

    def _set_fullscreen_placeholder(self, text: str) -> None:
        if self._fullscreen_preview and self._fullscreen_preview.isVisible():
            self._fullscreen_preview.set_placeholder(text)

    def _update_stream_info_badge(self, role_override: str | None = None) -> None:
        settings = self._stream_video_settings
        text = f"{settings.width}x{settings.height} | {settings.fps} FPS | {settings.codec.upper()}"
        role = role_override or "offline"
        if self._streamer_state == StreamerState.STREAMING.value:
            role = "success"
        elif self._streamer_state == StreamerState.STARTING.value:
            role = "waiting"
        elif self._streamer_state == StreamerState.ERROR.value:
            role = "error"
        self._stream_info_state = (text, role)
        if hasattr(self, "stream_info_badge"):
            self.stream_info_badge.set_state(*self._stream_info_state)
        self._sync_fullscreen_status()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is getattr(self, "preview_label", None)
            and event.type() == QEvent.Type.MouseButtonDblClick
        ):
            self._toggle_fullscreen_preview()
            return True
        return super().eventFilter(watched, event)

    # ── lifecycle ────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._fullscreen_preview:
            self._fullscreen_preview.close()
        self._preview_render_timer.stop()
        self._flush_log_lines()
        self._log_flush_timer.stop()
        self._ai_processor.stop()
        self._smart_alert_service.stop()
        self._video_receiver.stop()
        self._disconnect()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.preview_label.update()
