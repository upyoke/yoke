"""Visible worker-backed checking screens for the onboarding wizard."""

from __future__ import annotations

from typing import Any, Callable

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_state import _View


class CheckingFlow:
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
    ) -> None:
        self._checking = True
        self._checking_blocks_quit = blocks_quit
        if replace_current and self._history:
            self._history.pop()
        self._goto(_View(
            step,
            lambda: steps.checking_body(title, message, detail_lines),
        ))
        self.run_worker(
            lambda: self._checking_worker(work, on_success, on_error),
            thread=True,
            exclusive=True,
            group=group,
        )

    def _checking_worker(
        self,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - probe failures route to the TUI
            self._finish_checking_from_thread(on_success, on_error, None, exc)
            return
        self._finish_checking_from_thread(on_success, on_error, result, None)

    def _finish_checking_from_thread(
        self,
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        result: Any,
        exc: BaseException | None,
    ) -> None:
        try:
            self.call_from_thread(
                self._finish_checking,
                on_success,
                on_error,
                result,
                exc,
            )
        except RuntimeError:
            return

    def _finish_checking(
        self,
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        result: Any,
        exc: BaseException | None,
    ) -> None:
        if not self._checking:
            return
        self._checking = False
        self._checking_blocks_quit = False
        if self._history:
            self._history.pop()
        if exc is None:
            on_success(result)
            return
        on_error(exc)


__all__ = ["CheckingFlow"]
