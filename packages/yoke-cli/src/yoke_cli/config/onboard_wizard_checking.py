"""Visible worker-backed checking screens for the onboarding wizard."""

from __future__ import annotations

from typing import Any, Callable

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_state import _View


class CheckingFlow:
    # Each check takes a fresh token; a worker whose token no longer matches was
    # abandoned (Esc, or a newer check) and its late result is dropped.
    _checking_token: int = 0
    _checking_cancel: Callable[[], None] | None = None

    def _run_checking(
        self,
        *,
        step: str,
        title: str,
        message: str,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        detail_lines: list[str] | None = None,
        group: str = "onboard-check",
        replace_current: bool = False,
        blocks_quit: bool = False,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Show a checking view while ``work`` runs on a thread.

        ``on_cancel`` makes the check abandonable: Esc pops the checking view,
        drops the worker's eventual result, and calls it to route somewhere
        sensible. A check without it ignores Esc until the work finishes.
        """
        self._checking = True
        self._checking_blocks_quit = blocks_quit
        self._checking_cancel = on_cancel
        self._checking_token += 1
        token = self._checking_token
        if replace_current and self._history:
            self._history.pop()
        self._goto(_View(
            step,
            lambda: steps.checking_body(title, message, detail_lines),
        ))
        self.run_worker(
            lambda: self._checking_worker(token, work, on_success, on_error),
            thread=True,
            exclusive=True,
            group=group,
        )

    def _cancel_checking(self) -> bool:
        """Abandon the running check from Esc; False when it declared no route."""
        cancel = self._checking_cancel
        if not self._checking or cancel is None:
            return False
        self._checking = False
        self._checking_blocks_quit = False
        self._checking_cancel = None
        self._checking_token += 1
        if self._history:
            self._history.pop()
        cancel()
        return True

    def _checking_worker(
        self,
        token: int,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - probe failures route to the TUI
            self._finish_checking_from_thread(token, on_success, on_error, None, exc)
            return
        self._finish_checking_from_thread(token, on_success, on_error, result, None)

    def _finish_checking_from_thread(
        self,
        token: int,
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        result: Any,
        exc: BaseException | None,
    ) -> None:
        try:
            self.call_from_thread(
                self._finish_checking,
                token,
                on_success,
                on_error,
                result,
                exc,
            )
        except RuntimeError:
            return

    def _finish_checking(
        self,
        token: int,
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        result: Any,
        exc: BaseException | None,
    ) -> None:
        if not self._checking or token != self._checking_token:
            return
        self._checking = False
        self._checking_blocks_quit = False
        self._checking_cancel = None
        if self._history:
            self._history.pop()
        if exc is None:
            on_success(result)
            return
        on_error(exc)


__all__ = ["CheckingFlow"]
