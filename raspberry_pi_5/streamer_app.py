from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime

from shared.config import StreamerConfig
from shared.constants import DEFAULT_DEV_PIN
from shared.network import local_access_hint
from shared.state import StreamerState
from streamer.control_server import StreamerControlServer
from streamer.services.stream_service import StreamService
from streamer.state_machine import StreamerStateMachine


class StreamerTerminalApp:
    def __init__(self):
        self._closing = False
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

    def _emit_log(self, message: str) -> None:
        if self._closing:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def _on_state_changed(self, state: StreamerState, reason: str | None) -> None:
        if self._closing:
            return
        message = f"State changed to {state.value}."
        if reason:
            message = f"{message} Reason: {reason}"
        self._emit_log(message)

    def start(self):
        print("="*60)
        print(" SkyGuard Streamer - Raspberry Pi 5 Edition")
        print("="*60)
        
        self._control_server.start_background()
        
        self._emit_log("Streamer app launched. Waiting for authenticated START_STREAM.")
        
        if os.getenv("SKYGUARD_PIN"):
            self._emit_log("PIN loaded from SKYGUARD_PIN.")
        elif os.getenv("SIMPLE_STREAM_PIN"):
            self._emit_log("PIN loaded from legacy SIMPLE_STREAM_PIN.")
        else:
            self._emit_log(f"Development PIN active: {DEFAULT_DEV_PIN}.")

        print("-" * 60)
        print(f" Listening: {self._config.control_host}:{self._config.control_port}")
        print(f" Video UDP: {self._config.video_port}")
        print(f" Connect operator to: {local_access_hint(self._config.control_port)}")
        print("-" * 60)
        print(" Press Ctrl+C to exit")
        print("-" * 60)

        # Handle graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            while not self._closing:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self._shutdown()

    def _signal_handler(self, signum, frame):
        self._shutdown()

    def _shutdown(self):
        if self._closing:
            return
        self._closing = True
        print("\nShutting down SkyGuard Streamer...")
        self._control_server.stop_background()
        print("Shutdown complete.")
        sys.exit(0)


def main() -> int:
    app = StreamerTerminalApp()
    app.start()
    return 0
