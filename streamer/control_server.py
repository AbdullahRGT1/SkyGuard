from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import Any

try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets < 13
    from websockets import serve

from websockets.exceptions import ConnectionClosed

from shared.config import StreamerConfig
from shared.messages import ControlMessage, MessageType, error_message, state_message
from shared.security import create_nonce, verify_challenge_response
from shared.settings import VideoSettings
from shared.state import START_ALLOWED_FROM, STOP_ALLOWED_FROM, StreamerState
from streamer.services.stream_service import StreamService, StreamTarget
from streamer.state_machine import InvalidStateTransition, StreamerStateMachine


class StreamerControlServer:
    def __init__(
        self,
        config: StreamerConfig,
        state_machine: StreamerStateMachine,
        stream_service: StreamService,
        log: Callable[[str], None],
    ) -> None:
        self._config = config
        self._state_machine = state_machine
        self._stream_service = stream_service
        self._log = log
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._stop_requested = threading.Event()

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_requested.clear()
        self._started.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="streamer-control-server",
            daemon=True,
        )
        self._thread.start()

    def stop_background(self) -> None:
        self._stop_requested.set()
        if not self._loop:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
            return

        if self._started.is_set() and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            with contextlib.suppress(Exception):
                future.result(timeout=2)
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start())
            self._started.set()
            if not self._stop_requested.is_set():
                self._loop.run_forever()
            self._loop.run_until_complete(self._shutdown())
        finally:
            self._loop.close()
            self._loop = None

    async def _start(self) -> None:
        self._server = await serve(
            self._handle_client,
            self._config.control_host,
            self._config.control_port,
            ping_interval=10,
            ping_timeout=10,
        )
        if self._stop_requested.is_set():
            return
        self._state_machine.transition(StreamerState.READY_WAITING)
        self._log(
            f"Control server listening on "
            f"{self._config.control_host}:{self._config.control_port}."
        )

    async def _shutdown(self) -> None:
        await self._stream_service.stop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, websocket: Any) -> None:
        remote_host = self._remote_host(websocket)
        self._log(f"Operator connected from {remote_host}.")

        try:
            authenticated = await self._authenticate(websocket)
            if not authenticated:
                return

            await websocket.send(state_message(self._state_machine.current).to_json())

            async for raw in websocket:
                message = ControlMessage.from_json(raw)
                await self._handle_command(websocket, message)
        except ConnectionClosed:
            self._log(f"Operator disconnected from {remote_host}.")
        except Exception as exc:
            self._log(f"Control channel error: {exc}")

    async def _authenticate(self, websocket: Any) -> bool:
        nonce = create_nonce()
        await websocket.send(
            ControlMessage(
                type=MessageType.AUTH_CHALLENGE.value,
                payload={
                    "salt": self._config.pin_record.salt_hex,
                    "nonce": nonce,
                },
            ).to_json()
        )

        raw = await asyncio.wait_for(websocket.recv(), timeout=15)
        message = ControlMessage.from_json(raw)

        if message.type != MessageType.AUTH_RESPONSE.value:
            await websocket.send(
                error_message("AUTH_EXPECTED", "Authentication required.").to_json()
            )
            return False

        pin_proof = str(message.payload.get("pin_proof") or "")
        valid = verify_challenge_response(
            self._config.pin_record.key_hex,
            nonce,
            pin_proof,
        )

        if not valid:
            self._log("Authentication failed.")
            await websocket.send(
                ControlMessage(type=MessageType.AUTH_FAILED.value).to_json()
            )
            return False

        self._log("Operator authenticated.")
        await websocket.send(ControlMessage(type=MessageType.AUTH_OK.value).to_json())
        return True

    async def _handle_command(self, websocket: Any, message: ControlMessage) -> None:
        if message.type == MessageType.START_STREAM.value:
            await self._start_stream(websocket, message)
            return

        if message.type == MessageType.STOP_STREAM.value:
            await self._stop_stream(websocket)
            return

        if message.type == MessageType.HEARTBEAT.value:
            await websocket.send(state_message(self._state_machine.current).to_json())
            return

        await websocket.send(error_message("UNKNOWN_COMMAND", message.type).to_json())

    async def _start_stream(self, websocket: Any, message: ControlMessage) -> None:
        if self._state_machine.current not in START_ALLOWED_FROM:
            await websocket.send(
                error_message(
                    "INVALID_STATE",
                    f"Cannot start stream while state is {self._state_machine.current}.",
                ).to_json()
            )
            return

        try:
            target_host = self._remote_host(websocket)
            target_port = int(message.payload.get("video_port") or self._config.video_port)
            video_settings = VideoSettings.from_dict(message.payload.get("video_settings"))

            self._state_machine.transition(StreamerState.STARTING)
            await websocket.send(state_message(StreamerState.STARTING).to_json())

            await self._stream_service.start(
                StreamTarget(host=target_host, port=target_port),
                video_settings=video_settings,
            )
            effective_video_settings = self._stream_service.video_settings

            self._state_machine.transition(StreamerState.STREAMING)
            await websocket.send(
                state_message(
                    StreamerState.STREAMING,
                    video_host=target_host,
                    video_port=target_port,
                    video_settings=effective_video_settings.to_dict(),
                ).to_json()
            )
        except Exception as exc:
            await self._stream_service.stop()
            with contextlib.suppress(InvalidStateTransition):
                self._state_machine.transition(StreamerState.ERROR, reason=str(exc))
                self._state_machine.transition(StreamerState.READY_WAITING)
            await websocket.send(error_message("START_FAILED", str(exc)).to_json())
            await websocket.send(state_message(StreamerState.READY_WAITING).to_json())

    async def _stop_stream(self, websocket: Any) -> None:
        if self._state_machine.current not in STOP_ALLOWED_FROM:
            await websocket.send(state_message(self._state_machine.current).to_json())
            return

        try:
            self._state_machine.transition(StreamerState.STOPPING)
            await websocket.send(state_message(StreamerState.STOPPING).to_json())
            await self._stream_service.stop()
            self._state_machine.transition(StreamerState.READY_WAITING)
            await websocket.send(state_message(StreamerState.READY_WAITING).to_json())
        except Exception as exc:
            self._state_machine.transition(StreamerState.ERROR, reason=str(exc))
            await websocket.send(error_message("STOP_FAILED", str(exc)).to_json())
            await websocket.send(state_message(StreamerState.ERROR).to_json())

    @staticmethod
    def _remote_host(websocket: Any) -> str:
        remote_address = getattr(websocket, "remote_address", None)
        if isinstance(remote_address, tuple) and remote_address:
            return str(remote_address[0])
        return "127.0.0.1"
