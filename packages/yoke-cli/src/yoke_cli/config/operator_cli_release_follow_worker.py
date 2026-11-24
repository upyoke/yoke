"""Run one operator CLI follow at a time while the relay keeps polling."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from yoke_cli.config import operator_cli_release_follow
from yoke_cli.transport.installed_cli_staleness import update_recovery
from yoke_contracts.refusal_recovery import compose_refusal

_LOGGER = logging.getLogger(__name__)


class OperatorCliReleaseFollower:
    """Own follow attempts and keep them out of the relay's pin and restart."""

    def __init__(self, release: str, state_dir: Path) -> None:
        self._release = release
        self._state_dir = state_dir
        self._admission = Lock()
        self._paused = False
        self._thread: Thread | None = None
        self._record: dict[str, Any] | None = None

    def start(self) -> bool:
        """Start an attempt if there is no pin or unsettled follow."""
        with self._admission:
            if self._paused or self._thread is not None:
                return False
            thread = Thread(target=self._follow, name="operator-cli-release-follow", daemon=True)
            thread.start()
            self._thread = thread
            return True

    def settle(self) -> dict[str, Any] | None:
        """Take a finished attempt's record without waiting."""
        with self._admission:
            if self._thread is None or self._thread.is_alive():
                return None
            self._thread = None
            return self._record

    def pause_and_wait(self) -> None:
        """Called by the pin thread before it installs a new relay release."""
        with self._admission:
            self._paused = True
            thread = self._thread
        if thread is not None:
            thread.join()

    def resume(self) -> None:
        """Reopen admission after a failed pin keeps the current relay alive."""
        with self._admission:
            self._paused = False

    def _follow(self) -> None:
        try:
            self._record = operator_cli_release_follow.follow_release(
                self._release, self._state_dir
            )
        except Exception as exc:  # noqa: BLE001 - diagnose the failed background attempt
            _LOGGER.error(
                "%s",
                compose_refusal(
                    f"OPERATOR-CLI-FOLLOW-FAILED: could not follow release "
                    f"{self._release}: {type(exc).__name__}: {exc}.",
                    recovery=f"{update_recovery(self._release)}.",
                ),
            )
            self._record = {"outcome": "update_failed"}
