from __future__ import annotations

import json
from pathlib import Path
import threading

from ai_environment import environment_probe_code, installer_command, project_python, setup_script
from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
)
from settings_store import available_ai_models

from shared.settings import (
    AI_DEVICES,
    DEFAULT_AI_MODEL,
    RESOLUTION_PRESETS,
    VIDEO_CODECS,
    AiSettings,
    OperatorSettings,
    SmartAlertSettings,
    VideoSettings,
    ViolationCaptureSettings,
)
from shared.ui_theme import theme_manager
from shared.ui_widgets import AcrylicGlowFrame, CustomizeCard
from face_recognizer.n8n_sender import N8nSender


class FocusWheelSpinBox(SpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus() or self.lineEdit().hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class FocusWheelDoubleSpinBox(DoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus() or self.lineEdit().hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class SettingsPanel(QWidget):
    settings_applied = Signal(OperatorSettings)
    smart_alert_test_finished = Signal(str)

    def __init__(
        self,
        project_root: Path,
        settings: OperatorSettings,
        *,
        auto_refresh_environment: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("settingsView")
        self._project_root = project_root
        self._settings = settings
        self._models = available_ai_models(project_root) or [DEFAULT_AI_MODEL]
        self._env_process: QProcess | None = None
        self._env_output = ""

        theme_manager().register(self)
        self.smart_alert_test_finished.connect(self._set_smart_alert_status)
        self._build_ui()
        self.set_settings(settings)
        if auto_refresh_environment:
            self.refresh_ai_environment()
        else:
            self._set_env_probe_idle()

    # ── public API ───────────────────────────────────────────────

    def set_settings(self, settings: OperatorSettings) -> None:
        self._settings = settings

        self.ai_switch.setChecked(settings.ai.enabled)
        if settings.ai.model_name and settings.ai.model_name not in self._models:
            self._models.append(settings.ai.model_name)
            self.model_combo.addItem(settings.ai.model_name)
        self.model_combo.setCurrentText(settings.ai.model_name)
        self.device_combo.setCurrentText(settings.ai.device)
        self.conf_spin.setValue(settings.ai.conf)
        self.iou_spin.setValue(settings.ai.iou)
        self.imgsz_spin.setValue(settings.ai.imgsz)
        self.verbose_check.setChecked(settings.ai.verbose)
        self.capture_switch.setChecked(settings.violation_capture.enabled)
        self.capture_delay_spin.setValue(settings.violation_capture.stabilization_seconds)
        self.smart_alert_switch.setChecked(settings.smart_alerts.enabled)
        self.smart_alert_interval_spin.setValue(settings.smart_alerts.batch_interval_minutes)
        self.smart_alert_max_images_spin.setValue(settings.smart_alerts.max_images_per_batch)
        self.smart_alert_similarity_spin.setValue(settings.smart_alerts.face_similarity)
        self.smart_alert_group_check.setChecked(settings.smart_alerts.group_similar_faces)
        self.smart_alert_summary_check.setChecked(settings.smart_alerts.send_summary)
        self.smart_alert_delete_temp_check.setChecked(settings.smart_alerts.delete_temp_images)
        self.smart_alert_webhook_input.setText(settings.smart_alerts.webhook_url)

        self.camera_spin.setValue(settings.video.camera_index)
        self.resolution_combo.setCurrentText(settings.video.resolution_text)
        self.width_spin.setValue(settings.video.width)
        self.height_spin.setValue(settings.video.height)
        self.fps_spin.setValue(settings.video.fps)
        self.jpeg_quality_spin.setValue(settings.video.jpeg_quality)
        self.codec_combo.setCurrentText(settings.video.codec)
        self.h264_bitrate_spin.setValue(settings.video.h264_bitrate_kbps)
        self._sync_video_controls()

    def current_settings(self) -> OperatorSettings:
        resolution = self.resolution_combo.currentText()
        if resolution != "Custom" and "x" in resolution:
            width_text, height_text = resolution.split("x", maxsplit=1)
            width = int(width_text)
            height = int(height_text)
        else:
            width = int(self.width_spin.value())
            height = int(self.height_spin.value())

        return OperatorSettings(
            ai=AiSettings(
                enabled=self.ai_switch.isChecked(),
                model_name=self.model_combo.currentText() or DEFAULT_AI_MODEL,
                device=self.device_combo.currentText() or "auto",
                conf=float(self.conf_spin.value()),
                iou=float(self.iou_spin.value()),
                imgsz=int(self.imgsz_spin.value()),
                verbose=self.verbose_check.isChecked(),
            ).validated(),
            video=VideoSettings(
                camera_index=int(self.camera_spin.value()),
                width=width,
                height=height,
                fps=int(self.fps_spin.value()),
                jpeg_quality=int(self.jpeg_quality_spin.value()),
                codec=self.codec_combo.currentText() or "auto",
                h264_bitrate_kbps=int(self.h264_bitrate_spin.value()),
            ).validated(),
            violation_capture=ViolationCaptureSettings(
                enabled=self.capture_switch.isChecked(),
                stabilization_seconds=float(self.capture_delay_spin.value()),
            ).validated(),
            smart_alerts=SmartAlertSettings(
                enabled=self.smart_alert_switch.isChecked(),
                webhook_url=self.smart_alert_webhook_input.text().strip(),
                batch_interval_minutes=int(self.smart_alert_interval_spin.value()),
                max_images_per_batch=int(self.smart_alert_max_images_spin.value()),
                face_similarity=float(self.smart_alert_similarity_spin.value()),
                group_similar_faces=self.smart_alert_group_check.isChecked(),
                send_summary=self.smart_alert_summary_check.isChecked(),
                delete_temp_images=self.smart_alert_delete_temp_check.isChecked(),
            ).validated(),
        )

    def set_ai_status(self, status: str) -> None:
        self.ai_status_label.setText(status)

    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self) -> None:
        tokens = theme_manager().tokens()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(24)

        settings_title = SubtitleLabel("Settings")
        settings_title.setStyleSheet("font-size: 20px; font-weight: 800;")
        layout.addWidget(settings_title)

        # ── Customize card (premium glass) ───────────────────────
        self._customize_card = CustomizeCard()
        layout.addWidget(self._customize_card)

        # ── AI Environment ───────────────────────────────────────
        env_panel = self._panel()
        env_layout = QGridLayout(env_panel)
        env_layout.setContentsMargins(24, 22, 24, 22)
        env_layout.setHorizontalSpacing(18)
        env_layout.setVerticalSpacing(14)

        env_title = SubtitleLabel("AI Environment")
        env_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        env_layout.addWidget(env_title, 0, 0, 1, 4)

        self.env_backend_label = BodyLabel("Checking")
        self.env_torch_label = BodyLabel("-")
        self.env_cuda_label = BodyLabel("-")
        self.env_deps_label = BodyLabel("-")
        self.env_python_label = BodyLabel(str(project_python(self._project_root)))
        self.env_status_label = BodyLabel("")
        self.refresh_env_button = PushButton("Refresh")
        self.install_cpu_button = PushButton("Install CPU AI")
        self.install_cuda_button = PrimaryPushButton("Install CUDA AI")

        self.refresh_env_button.clicked.connect(self.refresh_ai_environment)
        self.install_cpu_button.clicked.connect(lambda: self._install_ai_backend("cpu"))
        self.install_cuda_button.clicked.connect(lambda: self._install_ai_backend("cuda"))

        label_style = f"color: {tokens.text_secondary}; font-size: 12px;"
        for lbl_text, row, col in [
            ("Backend", 1, 0), ("PyTorch", 1, 2),
            ("CUDA", 2, 0), ("Packages", 2, 2),
            ("Python", 3, 0),
        ]:
            lbl = BodyLabel(lbl_text)
            lbl.setStyleSheet(label_style)
            env_layout.addWidget(lbl, row, col)

        env_layout.addWidget(self.env_backend_label, 1, 1)
        env_layout.addWidget(self.env_torch_label, 1, 3)
        env_layout.addWidget(self.env_cuda_label, 2, 1)
        env_layout.addWidget(self.env_deps_label, 2, 3)
        env_layout.addWidget(self.env_python_label, 3, 1, 1, 3)
        env_layout.addWidget(self.env_status_label, 4, 0, 1, 2)
        env_layout.addWidget(self.refresh_env_button, 4, 2)
        env_layout.addWidget(self.install_cpu_button, 4, 3)
        env_layout.addWidget(self.install_cuda_button, 5, 3)
        env_layout.setColumnStretch(3, 1)

        # ── AI Detection ─────────────────────────────────────────
        ai_panel = self._panel()
        ai_layout = QGridLayout(ai_panel)
        ai_layout.setContentsMargins(24, 22, 24, 22)
        ai_layout.setHorizontalSpacing(18)
        ai_layout.setVerticalSpacing(14)

        ai_title = SubtitleLabel("AI Detection")
        ai_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        ai_layout.addWidget(ai_title, 0, 0, 1, 4)

        self.ai_switch = SwitchButton()
        self.model_combo = ComboBox()
        self.model_combo.addItems(self._models)
        self.device_combo = ComboBox()
        self.device_combo.addItems(list(AI_DEVICES))
        self.conf_spin = FocusWheelDoubleSpinBox()
        self.conf_spin.setRange(0.01, 1.0)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setDecimals(2)
        self.iou_spin = FocusWheelDoubleSpinBox()
        self.iou_spin.setRange(0.01, 1.0)
        self.iou_spin.setSingleStep(0.05)
        self.iou_spin.setDecimals(2)
        self.imgsz_spin = FocusWheelSpinBox()
        self.imgsz_spin.setRange(160, 1280)
        self.imgsz_spin.setSingleStep(32)
        self.verbose_check = CheckBox("Verbose")
        self.ai_status_label = BodyLabel("Disabled")
        self.capture_switch = SwitchButton()
        self.capture_delay_spin = FocusWheelDoubleSpinBox()
        self.capture_delay_spin.setRange(0.0, 30.0)
        self.capture_delay_spin.setSingleStep(0.5)
        self.capture_delay_spin.setDecimals(1)

        for lbl_text, row, col in [
            ("Enable", 1, 0), ("Model", 1, 2),
            ("Device", 2, 0), ("conf", 2, 2),
            ("iou", 3, 0), ("imgsz", 3, 2),
            ("AI status", 4, 2),
            ("Violation capture", 5, 0), ("Stabilization seconds", 5, 2),
        ]:
            lbl = BodyLabel(lbl_text)
            lbl.setStyleSheet(label_style)
            ai_layout.addWidget(lbl, row, col)

        ai_layout.addWidget(self.ai_switch, 1, 1)
        ai_layout.addWidget(self.model_combo, 1, 3)
        ai_layout.addWidget(self.device_combo, 2, 1)
        ai_layout.addWidget(self.conf_spin, 2, 3)
        ai_layout.addWidget(self.iou_spin, 3, 1)
        ai_layout.addWidget(self.imgsz_spin, 3, 3)
        ai_layout.addWidget(self.verbose_check, 4, 0)
        ai_layout.addWidget(self.ai_status_label, 4, 3)
        ai_layout.addWidget(self.capture_switch, 5, 1)
        ai_layout.addWidget(self.capture_delay_spin, 5, 3)
        ai_layout.setColumnStretch(3, 1)

        # ── Video Settings ───────────────────────────────────────
        video_panel = self._panel()
        video_layout = QGridLayout(video_panel)
        video_layout.setContentsMargins(24, 22, 24, 22)
        video_layout.setHorizontalSpacing(18)
        video_layout.setVerticalSpacing(14)

        video_title = SubtitleLabel("Video Settings")
        video_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        video_layout.addWidget(video_title, 0, 0, 1, 4)

        self.camera_spin = FocusWheelSpinBox()
        self.camera_spin.setRange(0, 16)
        self.resolution_combo = ComboBox()
        self.resolution_combo.addItems(list(RESOLUTION_PRESETS))
        self.width_spin = FocusWheelSpinBox()
        self.width_spin.setRange(160, 3840)
        self.width_spin.setSingleStep(160)
        self.height_spin = FocusWheelSpinBox()
        self.height_spin.setRange(120, 2160)
        self.height_spin.setSingleStep(120)
        self.fps_spin = FocusWheelSpinBox()
        self.fps_spin.setRange(1, 60)
        self.jpeg_quality_spin = FocusWheelSpinBox()
        self.jpeg_quality_spin.setRange(30, 95)
        self.codec_combo = ComboBox()
        self.codec_combo.addItems(list(VIDEO_CODECS))
        self.h264_bitrate_spin = FocusWheelSpinBox()
        self.h264_bitrate_spin.setRange(256, 50_000)
        self.h264_bitrate_spin.setSingleStep(250)

        self.resolution_combo.currentTextChanged.connect(self._sync_video_controls)
        self.codec_combo.currentTextChanged.connect(self._sync_video_controls)

        for lbl_text, row, col in [
            ("Camera index", 1, 0), ("Resolution", 1, 2),
            ("Width", 2, 0), ("Height", 2, 2),
            ("FPS", 3, 0), ("JPEG quality", 3, 2),
            ("Codec", 4, 0), ("H.264 bitrate kbps", 4, 2),
        ]:
            lbl = BodyLabel(lbl_text)
            lbl.setStyleSheet(label_style)
            video_layout.addWidget(lbl, row, col)

        video_layout.addWidget(self.camera_spin, 1, 1)
        video_layout.addWidget(self.resolution_combo, 1, 3)
        video_layout.addWidget(self.width_spin, 2, 1)
        video_layout.addWidget(self.height_spin, 2, 3)
        video_layout.addWidget(self.fps_spin, 3, 1)
        video_layout.addWidget(self.jpeg_quality_spin, 3, 3)
        video_layout.addWidget(self.codec_combo, 4, 1)
        video_layout.addWidget(self.h264_bitrate_spin, 4, 3)
        video_layout.setColumnStretch(3, 1)

        smart_panel = self._panel()
        smart_layout = QGridLayout(smart_panel)
        smart_layout.setContentsMargins(24, 22, 24, 22)
        smart_layout.setHorizontalSpacing(18)
        smart_layout.setVerticalSpacing(14)

        smart_title = SubtitleLabel("Smart Alerts")
        smart_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        smart_layout.addWidget(smart_title, 0, 0, 1, 4)

        self.smart_alert_switch = SwitchButton()
        self.smart_alert_interval_spin = FocusWheelSpinBox()
        self.smart_alert_interval_spin.setRange(1, 60)
        self.smart_alert_max_images_spin = FocusWheelSpinBox()
        self.smart_alert_max_images_spin.setRange(1, 10)
        self.smart_alert_similarity_spin = FocusWheelDoubleSpinBox()
        self.smart_alert_similarity_spin.setRange(0.10, 0.99)
        self.smart_alert_similarity_spin.setSingleStep(0.05)
        self.smart_alert_similarity_spin.setDecimals(2)
        self.smart_alert_group_check = CheckBox("Group Similar Faces")
        self.smart_alert_summary_check = CheckBox("Send Summary")
        self.smart_alert_delete_temp_check = CheckBox("Delete Temp Records")
        self.smart_alert_webhook_input = LineEdit()
        self.smart_alert_webhook_input.setPlaceholderText("https://n8n.example/webhook/skyguard")
        self.smart_alert_test_button = PushButton("Test")
        self.smart_alert_status_label = BodyLabel("")
        self.smart_alert_test_button.clicked.connect(self._test_smart_alert_webhook)

        for lbl_text, row, col in [
            ("Enable Smart Alerts", 1, 0), ("Batch interval minutes", 1, 2),
            ("Max images", 2, 0), ("Face similarity", 2, 2),
            ("Webhook URL", 4, 0),
        ]:
            lbl = BodyLabel(lbl_text)
            lbl.setStyleSheet(label_style)
            smart_layout.addWidget(lbl, row, col)

        smart_layout.addWidget(self.smart_alert_switch, 1, 1)
        smart_layout.addWidget(self.smart_alert_interval_spin, 1, 3)
        smart_layout.addWidget(self.smart_alert_max_images_spin, 2, 1)
        smart_layout.addWidget(self.smart_alert_similarity_spin, 2, 3)
        smart_layout.addWidget(self.smart_alert_group_check, 3, 0)
        smart_layout.addWidget(self.smart_alert_summary_check, 3, 1)
        smart_layout.addWidget(self.smart_alert_delete_temp_check, 3, 2)
        smart_layout.addWidget(self.smart_alert_webhook_input, 4, 1, 1, 2)
        smart_layout.addWidget(self.smart_alert_test_button, 4, 3)
        smart_layout.addWidget(self.smart_alert_status_label, 5, 0, 1, 4)
        smart_layout.setColumnStretch(2, 1)

        # ── Action buttons ───────────────────────────────────────
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.reset_button = PushButton("Reset Defaults")
        self.apply_button = PrimaryPushButton("Apply")
        self.reset_button.clicked.connect(self._reset_defaults)
        self.apply_button.clicked.connect(self._apply)
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.apply_button)

        layout.addWidget(env_panel)
        layout.addWidget(ai_panel)
        layout.addWidget(video_panel)
        layout.addWidget(smart_panel)
        layout.addLayout(button_row)
        layout.addStretch(1)

    # ── AI environment probe ─────────────────────────────────────

    def refresh_ai_environment(self) -> None:
        if self._env_process and self._env_process.state() != QProcess.ProcessState.NotRunning:
            return

        python_exe = project_python(self._project_root)
        if not python_exe.exists():
            self.env_status_label.setText("Python environment was not found.")
            return

        self._env_output = ""
        self.env_backend_label.setText("Checking")
        self.env_torch_label.setText("-")
        self.env_cuda_label.setText("-")
        self.env_deps_label.setText("-")
        self.env_python_label.setText(str(python_exe))
        self.env_status_label.setText("Checking AI environment...")

        process = QProcess(self)
        process.setProgram(str(python_exe))
        process.setArguments(["-c", environment_probe_code()])
        process.setWorkingDirectory(str(self._project_root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.started.connect(
            lambda: self.env_status_label.setText("AI environment probe started...")
        )
        process.readyReadStandardOutput.connect(self._read_env_output)
        process.finished.connect(self._env_check_finished)
        process.errorOccurred.connect(self._env_check_error)
        self._env_process = process
        process.start()
        QTimer.singleShot(30_000, self._cancel_stuck_env_check)

        if not process.waitForStarted(1000):
            self._env_check_error(process.error())

    def _set_env_probe_idle(self) -> None:
        python_exe = project_python(self._project_root)
        self.env_backend_label.setText("Not checked")
        self.env_torch_label.setText("-")
        self.env_cuda_label.setText("-")
        self.env_deps_label.setText("-")
        self.env_python_label.setText(str(python_exe))
        self.env_status_label.setText("Click Refresh to inspect the AI environment.")

    def _read_env_output(self) -> None:
        if not self._env_process:
            return
        chunk = bytes(self._env_process.readAllStandardOutput()).decode(
            "utf-8",
            errors="replace",
        )
        self._env_output += chunk

    def _env_check_error(self, error) -> None:
        if not self._env_process:
            return
        self.env_backend_label.setText("Unknown")
        self.env_status_label.setText(
            f"Could not start AI environment check: {self._env_process.errorString() or error}"
        )
        self._env_process = None

    def _cancel_stuck_env_check(self) -> None:
        if not self._env_process:
            return
        if self._env_process.state() == QProcess.ProcessState.NotRunning:
            return
        self._env_process.kill()
        self._env_process = None
        self.env_backend_label.setText("Timeout")
        self.env_status_label.setText("AI environment check timed out after 30 seconds.")

    def _env_check_finished(self, exit_code: int, _exit_status) -> None:
        self._read_env_output()
        self._env_process = None

        lines = [line.strip() for line in self._env_output.splitlines() if line.strip()]
        if exit_code != 0 or not lines:
            self.env_status_label.setText("Could not inspect AI environment.")
            self.env_backend_label.setText("Unknown")
            return

        json_line = ""
        for line in reversed(lines):
            if line.startswith("{") and line.endswith("}"):
                json_line = line
                break

        try:
            status = json.loads(json_line)
        except json.JSONDecodeError:
            preview = " | ".join(lines[-3:])
            self.env_status_label.setText(
                "AI environment check returned invalid output: "
                f"{preview[:220]}"
            )
            self.env_backend_label.setText("Unknown")
            return

        torch_version = str(status.get("torch_version") or "Not installed")
        cuda_available = bool(status.get("cuda_available"))
        cuda_device = str(status.get("cuda_device") or "")
        deps = [
            f"ultralytics: {'OK' if status.get('ultralytics_installed') else 'Missing'}",
            f"cvzone: {'OK' if status.get('cvzone_installed') else 'Missing'}",
            f"insightface: {'OK' if status.get('insightface_installed') else 'Missing'}",
            f"onnxruntime: {'OK' if status.get('onnxruntime_installed') else 'Missing'}",
        ]
        providers = status.get("onnx_providers") or []
        if providers:
            deps.append("providers: " + ",".join(str(item) for item in providers))

        self.env_backend_label.setText(str(status.get("backend") or "Unknown"))
        self.env_torch_label.setText(torch_version)
        self.env_cuda_label.setText(
            f"Available — {cuda_device}" if cuda_available else "Unavailable"
        )
        self.env_deps_label.setText(" | ".join(deps))

        error = str(status.get("error") or "")
        if error:
            self.env_status_label.setText(error)
        else:
            self.env_status_label.setText("AI environment check complete.")

    def _install_ai_backend(self, backend: str) -> None:
        script = setup_script(self._project_root, backend)
        if not script.exists():
            self.env_status_label.setText(f"Installer script was not found: {script}")
            return

        backend_label = "CUDA" if backend == "cuda" else "CPU"
        answer = QMessageBox.question(
            self,
            f"Install {backend_label} AI",
            (
                f"This will uninstall the current torch, torchvision, and torchaudio "
                f"packages, then install the {backend_label} AI environment.\n\n"
                "A separate PowerShell installer window will open. Restart the operator "
                "app after installation finishes."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        program, arguments = installer_command(self._project_root, backend)
        started = QProcess.startDetached(program, arguments, str(self._project_root))
        if not started:
            self.env_status_label.setText("Could not launch AI installer.")
            return

        self.env_status_label.setText(
            f"{backend_label} installer launched. Restart after it completes."
        )

    # ── helpers ──────────────────────────────────────────────────

    def _sync_video_controls(self, *_args) -> None:
        is_custom = self.resolution_combo.currentText() == "Custom"
        self.width_spin.setEnabled(is_custom)
        self.height_spin.setEnabled(is_custom)
        self.h264_bitrate_spin.setEnabled(self.codec_combo.currentText() in {"auto", "h264"})

    @staticmethod
    def _panel() -> AcrylicGlowFrame:
        return AcrylicGlowFrame()

    def _reset_defaults(self) -> None:
        self.set_settings(OperatorSettings())

    def _apply(self) -> None:
        settings = self.current_settings()
        self._settings = settings
        self.settings_applied.emit(settings)

    def _test_smart_alert_webhook(self) -> None:
        webhook_url = self.smart_alert_webhook_input.text().strip()
        if not webhook_url:
            self._set_smart_alert_status("Enter a webhook URL first.")
            return

        self._set_smart_alert_status("Sending test webhook...")
        self.smart_alert_test_button.setEnabled(False)

        def worker() -> None:
            try:
                N8nSender().send(
                    webhook_url,
                    {
                        "source": "SkyGuard Operator",
                        "test": True,
                        "summary_text": "SkyGuard Smart Alerts test webhook.",
                    },
                    [],
                )
            except Exception as exc:
                self.smart_alert_test_finished.emit(f"Test failed: {exc}")
                return
            self.smart_alert_test_finished.emit("Test webhook sent.")

        threading.Thread(
            target=worker,
            name="smart-alert-webhook-test",
            daemon=True,
        ).start()

    def _set_smart_alert_status(self, message: str) -> None:
        self.smart_alert_status_label.setText(message)
        self.smart_alert_test_button.setEnabled(True)
