"""Structural shell protocols shared by onboarding flow mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class CloneFlowShell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(
        self,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        validate=None,
        initial_value: str = "",
    ) -> None: ...
    def _goto_project_details(self) -> None: ...
    def _goto_owner_picker(self) -> None: ...
    def _after_repo(self, value: str) -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _after_existing_project_ready(self) -> None: ...
    def _materialize_and_inspect_checkout(self) -> None: ...
    async def action_back(self) -> None: ...


class ConnectFlowShell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _history: list[Any]
    _stored_yoke_token_available: bool
    _stored_yoke_attempted: bool

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(
        self, step, title, subtitle, rows, on_select, *, initial: int = 0
    ) -> "_View": ...
    def _goto_input(
        self,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        initial_value: str = "",
    ) -> None: ...
    def _goto_machine_github(self) -> None: ...
    def _return_to_destination_picker(self, *, drop_current: bool = True) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _render_current(self) -> None: ...
    def _begin_form(self, fields, *, on_done) -> None: ...
    def _submit_pending_form(self) -> bool: ...


__all__ = ["CloneFlowShell", "ConnectFlowShell"]
