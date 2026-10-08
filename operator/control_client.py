from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import Any

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets import connect

from websockets.exceptions import ConnectionClosed

from shared.messages import ControlMessage, MessageType
from shared.network import ControlEndpoint
from shared.security import sign_challenge
from shared.settings import VideoSettings


class OperatorControlClient:
    def __init__(
        self,
        log: Callable[[str], None],
        state_changed: Callable[[str], None],
        connection_changed: Callable[[str], None],
        stream_info_changed: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._log = log
        self._state_changed = state_changed
        self._connection_changed = connection_changed
        self._stream_info_changed = stream_info_changed or (lambda _payload: None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._websocket: Any = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()

    def connect_background(self, endpoint: ControlEndpoint, pin: str) -> None:
        if self._thread and self._thread.is_alive():
            self._log("Control client is already running.")
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(endpoint, pin),
            name="operator-control-client",
            daemon=True,
        )
        self._thread.start()

    def disconnect(self) -> None:
        if not self._loop or self._loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
        with contextlib.suppress(Exception):
            future.result(timeout=2)
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def send_start_stream(
        self,
        video_port: int,
        video_settings: VideoSettings | None = None,
    ) -> None:
        if not self._connected.is_set():
            self._log("Connect and authenticate before sending START_STREAM.")
            return

        payload = {"video_port": video_port}
        if video_settings:
            payload["video_settings"] = video_settings.to_dict()

        self._submit(
            self._send(
                ControlMessage(
                    type=MessageType.START_STREAM.value,
                    payload=payload,
                )
            )
        )

    def send_stop_stream(self) -> None:
        if not self._connected.is_set():
            self._log("Connect and authenticate before sending STOP_STREAM.")
            return

        self._submit(self._send(ControlMessage(type=MessageType.STOP_STREAM.value)))

    def _run_loop(self, endpoint: ControlEndpoint, pin: str) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._connect_and_listen(endpoint, pin))
        self._loop.run_forever()
        self._loop.close()

    async def _connect_and_listen(self, endpoint: ControlEndpoint, pin: str) -> None:
        uri = endpoint.uri
        self._connection_changed("CONNECTING")
        self._log(f"Connecting to {uri}.")

        try:
            self._websocket = await connect(uri, ping_interval=10, ping_timeout=10)
            challenge = ControlMessage.from_json(await self._websocket.recv())
            if challenge.type != MessageType.AUTH_CHALLENGE.value:
                raise RuntimeError("Streamer did not send authentication challenge.")

            proof = sign_challenge(
                pin=pin,
                salt_hex=str(challenge.payload["salt"]),
                nonce_hex=str(challenge.payload["nonce"]),
            )
            await self._websocket.send(
                ControlMessage(
                    type=MessageType.AUTH_RESPONSE.value,
                    payload={"pin_proof": proof},
                ).to_json()
            )

            auth_result = ControlMessage.from_json(await self._websocket.recv())
            if auth_result.type != MessageType.AUTH_OK.value:
                raise RuntimeError(
                    "Authentication failed. Check that the PIN matches the streamer "
                    "SKYGUARD_PIN. The starter default is 1234."
                )

            self._connected.set()
            self._connection_changed("AUTHENTICATED")
            self._log("Authenticated with streamer.")

            async for raw in self._websocket:
                message = ControlMessage.from_json(raw)
                self._handle_message(message)
        except ConnectionClosed:
            self._log("Control connection closed.")
        except Exception as exc:
            self._log(f"Control client error: {exc}")
            self._connection_changed("ERROR")
        finally:
            self._connected.clear()
            await self._close()
            self._connection_changed("DISCONNECTED")
            asyncio.get_running_loop().call_soon(asyncio.get_running_loop().stop)

    def _handle_message(self, message: ControlMessage) -> None:
        if message.type == MessageType.STATE.value:
            state = str(message.payload.get("state") or "UNKNOWN")
            if "video_settings" in message.payload or "video_port" in message.payload:
                self._stream_info_changed(dict(message.payload))
            self._state_changed(state)
            self._log(f"Streamer state: {state}")
            return

        if message.type == MessageType.ERROR.value:
            self._log(
                f"Streamer error: {message.payload.get('code')} - "
                f"{message.payload.get('message')}"
            )
            self._state_changed("ERROR")
            return

        self._log(f"Received {message.type}.")

    async def _send(self, message: ControlMessage) -> None:
        if not self._websocket:
            self._log("Cannot send command because the control channel is disconnected.")
            return
        await self._websocket.send(message.to_json())

    async def _close(self) -> None:
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    def _submit(self, coroutine: Any) -> None:
        if not self._loop or self._loop.is_closed():
            self._log("Control loop is not running.")
            with contextlib.suppress(Exception):
                coroutine.close()
            return
        asyncio.run_coroutine_threadsafe(coroutine, self._loop)
