"""Existing-project lookup error and bounded-history recovery views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol

from yoke_cli.config import onboard_existing_project
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    _history: list[Any]

    def _goto(self, view: "_View") -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _render_current(self) -> None: ...


class ExistingProjectLookupRecoveryFlow:
    def _goto_existing_project_lookup_error(
        self: _Shell,
        exc: BaseException,
        *,
        retry: Callable[[], None],
        local_destination: bool = False,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        rows = [
            SelectionRow("retry", "Try again", "rerun the project check"),
            SelectionRow("back", "Back", "choose a different project option"),
        ]
        hint = onboard_existing_project.lookup_error_hint(
            local_destination=local_destination,
        )
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Can't use that Yoke project.",
                str(exc),
                [hint],
                rows,
                ok=False,
            ),
            lambda choice: self._on_existing_project_lookup_error(
                choice,
                retry=retry,
            ),
        ))

    def _on_existing_project_lookup_error(
        self: _Shell,
        choice: str,
        *,
        retry: Callable[[], None],
    ) -> None:
        if choice == "retry":
            if self._history:
                self._history.pop()
            retry()
            return
        self._return_to_project_mode()

    def _return_to_project_mode(self: _Shell) -> None:
        target = getattr(self, "_project_mode_view", None)
        for index in range(len(self._history) - 1, -1, -1):
            if self._history[index] is target:
                del self._history[index + 1:]
                self._render_current()
                return
        if self._history:
            self._history.pop()
        self._goto_project_mode()


__all__ = ["ExistingProjectLookupRecoveryFlow"]
