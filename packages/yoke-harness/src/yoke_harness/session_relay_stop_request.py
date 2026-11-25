"""Track the relay stop request and translate termination signals into it."""

from __future__ import annotations

import logging
import signal
import time

from yoke_harness.session_relay_supervision import RelayStopRequested


_LOGGER = logging.getLogger(__name__)


class StopRequest:
    """Publish the main thread's stop reason and deadline start to workers."""

    def __init__(self) -> None:
        self._state = ("", 0.0)

    def set(self, reason: str, *, replace: bool = False) -> None:
        # SIGTERM can interrupt the main thread while it holds a lock.
        # Publish both values together without acquiring one in the handler.
        if not self.reason or replace:
            self._state = (reason, time.monotonic())

    @property
    def reason(self) -> str:
        return self._state[0]

    @property
    def requested_at(self) -> float:
        return self._state[1]

    def is_set(self) -> bool:
        return bool(self.reason)


def install_signal_handlers(stop: StopRequest) -> dict[int, object]:
    """Route termination signals into the stop request; return what they replaced."""

    def handle(signum: int, _frame: object) -> None:
        if not stop.reason.startswith("signal:"):
            stop.set(f"signal:{signal.Signals(signum).name}", replace=True)
            raise RelayStopRequested()

    previous: dict[int, object] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.signal(signum, handle)
        except ValueError:
            # Not the main thread — a caller driving the loop directly owns
            # its own stop signal, so this is not an error.
            _LOGGER.debug("relay daemon could not install %s handler", signum)
    return previous


def restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            _LOGGER.debug("relay daemon could not restore %s handler", signum)
