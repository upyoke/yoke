"""Selection and single-input view constructors shared by every wizard flow."""

from __future__ import annotations

from typing import Protocol

from textual.widgets import Static

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_state import _PendingInput, _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    _pending_input: _PendingInput | None

    def _goto(self, view: _View) -> None: ...


class ViewHelpers:
    def _selection_view(self: _Shell, step, title, subtitle, rows, on_select,
                        *, initial: int = 0) -> _View:
        return _View(
            step,
            lambda: steps.selection_body(title, subtitle, rows, initial=initial),
            on_select,
        )

    def _input_view(
        self: _Shell, step, title, subtitle, *, placeholder, on_done,
        password=False, allow_placeholder=True, validate=None,
        initial_value: str = "",
    ) -> _View:
        def builder() -> list[Static]:
            self._pending_input = _PendingInput(
                on_done=on_done,
                placeholder=placeholder,
                allow_placeholder=allow_placeholder,
                validate=validate,
            )
            return steps.input_body(
                title,
                subtitle,
                placeholder,
                password,
                initial_value=initial_value,
            )
        return _View(step, builder)

    def _goto_input(self: _Shell, step, title, subtitle, *, placeholder, on_done,
                    password=False, allow_placeholder=True, validate=None,
                    initial_value: str = "") -> None:
        self._goto(self._input_view(
            step, title, subtitle, placeholder=placeholder,
            on_done=on_done, password=password,
            allow_placeholder=allow_placeholder, validate=validate,
            initial_value=initial_value,
        ))


__all__ = ["ViewHelpers"]
