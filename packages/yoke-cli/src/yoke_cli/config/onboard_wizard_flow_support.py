"""Shared seams and structural types for onboarding wizard flows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import github_publish

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


def fetch_repo_owners(api_url: str, token: str) -> list:
    """List repository owners; tests patch this seam instead of using GitHub."""
    return github_publish.list_repo_owners(api_url, token)


class WizardShell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _pending_stored_project_checkout: str | None
    _project_mode_preset: bool
    _project_preset_attempted: bool
    _stored_project_attempted: bool
    _stored_project_checkouts: list[Any]

    def _goto(self, view: _View) -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> _View: ...
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
    def _start_dev_flow(self) -> None: ...
    def _check_project_git(self, mode: str) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_hosting(self) -> None: ...
    def _goto_board_art_intro(self) -> None: ...
    def _goto_stored_project_picker(self) -> None: ...
