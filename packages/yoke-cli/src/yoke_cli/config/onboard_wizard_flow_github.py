"""Machine GitHub App step for the ``yoke onboard`` wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import github_machine_verify
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB


def verify_machine_github_token(api_url: str, token: str) -> dict[str, Any]:
    """Legacy network seam retained for older publish/clone flows."""
    return github_machine_verify.verify(api_url, token)


def _wizard_steps():
    from yoke_cli.config import onboard_wizard_steps as steps

    return steps


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None
    _stored_machine_github_token_file: str | None

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class MachineGithubFlow:
    """Machine GitHub App routing screens."""

    def _goto_machine_github(self: _Shell) -> None:
        steps = _wizard_steps()
        self._goto(self._selection_view(
            STEP_GITHUB,
            onboard_github_copy.MACHINE_TOKEN_TITLE,
            onboard_github_copy.MACHINE_TOKEN_SUBTITLE,
            steps.MACHINE_GITHUB_ROWS, self._on_machine_github,
        ))

    def _on_machine_github(self: _Shell, choice: str) -> None:
        self.result.machine_github_choice = choice
        if choice != onboard_machine_github.CHOICE_CONNECT:
            self._goto_project_mode()
            return
        self._goto_machine_github_unavailable()

    def _goto_machine_github_unavailable(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub App connection is not available here yet.",
                (
                    "This setup flow no longer accepts manual GitHub credentials. "
                    "Continue backlog-only for now."
                ),
                [
                    "GitHub issue sync, PRs, Actions, and repo automation stay off.",
                    "You can connect GitHub after the App browser flow is available.",
                ],
                steps.GITHUB_APP_UNAVAILABLE_ROWS,
                ok=False,
            ),
            self._on_machine_github_unavailable,
        ))

    def _on_machine_github_unavailable(self: _Shell, choice: str) -> None:
        if choice == "backlog":
            self.result.machine_github_choice = onboard_machine_github.CHOICE_SKIP
            self._goto_project_mode()
            return
        self._goto_machine_github()

__all__ = ["MachineGithubFlow", "verify_machine_github_token"]
