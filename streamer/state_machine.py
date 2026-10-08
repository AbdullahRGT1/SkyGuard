from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from shared.state import StreamerState


class InvalidStateTransition(RuntimeError):
    pass


class StreamerStateMachine:
    _valid_transitions = {
        StreamerState.BOOTING: {StreamerState.READY_WAITING, StreamerState.ERROR},
        StreamerState.READY_WAITING: {StreamerState.AUTH_CHECK, StreamerState.STARTING},
        StreamerState.AUTH_CHECK: {StreamerState.READY_WAITING, StreamerState.STARTING},
        StreamerState.STARTING: {
            StreamerState.STREAMING,
            StreamerState.STOPPING,
            StreamerState.ERROR,
        },
        StreamerState.STREAMING: {StreamerState.STOPPING, StreamerState.ERROR},
        StreamerState.STOPPING: {StreamerState.READY_WAITING, StreamerState.ERROR},
        StreamerState.ERROR: {StreamerState.READY_WAITING},
    }

    def __init__(self) -> None:
        self._state = StreamerState.BOOTING
        self._lock = RLock()
        self._listeners: list[Callable[[StreamerState, str | None], None]] = []

    @property
    def current(self) -> StreamerState:
        with self._lock:
            return self._state

    def add_listener(self, callback: Callable[[StreamerState, str | None], None]) -> None:
        self._listeners.append(callback)

    def transition(self, target: StreamerState, reason: str | None = None) -> StreamerState:
        with self._lock:
            current = self._state
            if target == current:
                return current

            allowed = self._valid_transitions.get(current, set())
            if target not in allowed:
                raise InvalidStateTransition(f"Cannot transition from {current} to {target}")

            self._state = target
            listeners = list(self._listeners)

        for callback in listeners:
            callback(target, reason)

        return target
