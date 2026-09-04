"""Announce a project Yoke already has before asking anything about it.

Finding an existing project is the most consequential thing onboarding can
discover about a repository, so it is the headline the operator reads before
making any choice, and connecting to it is the answer already under the
cursor. Setting up a separate project for the same code stays available, one
row down, because it is the rare answer rather than the safe one.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from yoke_cli.config import onboard_existing_project
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow

CHOICE_CONNECT = "connect"
CHOICE_NEW_PROJECT = "new-project"

DETECTED_ROWS = [
    SelectionRow(
        CHOICE_CONNECT, "Connect to it",
        "reuse this project's board, issues, and settings",
    ),
    SelectionRow(
        CHOICE_NEW_PROJECT, "Set up a separate project instead",
        "ignore the match and create a new one",
    ),
]


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view) -> None: ...
    def _goto_existing_project_ready(
        self, *, on_choice: Callable[[str], None] | None = None,
    ) -> None: ...
    def _after_existing_project_ready(self) -> None: ...
    def _goto_slug(self) -> None: ...
    def _goto_clone_folder(self) -> None: ...


def match_detail_lines(result: Any) -> list[str]:
    """Everything known about the match, most locating fact first."""
    details = onboard_existing_project.match_lines(result) + [
        f"Project id: {result.existing_project_id} (env {result.env_name})",
        f"Project: {result.project_slug}",
    ]
    if result.project_checkout:
        checkout_label = (
            "Clone target"
            if result.project_mode in onboard_project.PROJECT_REMOTE_MODES
            else "Checkout"
        )
        details.insert(0, f"{checkout_label}: {result.project_checkout}")
    for label, value in (
        ("GitHub repo", result.project_github_repo),
        ("Issue prefix", result.project_public_item_prefix),
        ("Default branch", result.project_default_branch),
    ):
        if value:
            details.append(f"{label}: {value}")
    return details


class ExistingProjectDetectedFlow:
    """The detection screen and how its two answers route on each path."""

    def _goto_existing_project_ready(
        self: _Shell,
        *,
        on_choice: Callable[[str], None] | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    f"Existing Yoke project found: {self.result.project_slug}.",
                    onboard_existing_project.match_summary(self.result),
                    match_detail_lines(self.result),
                    DETECTED_ROWS,
                    ok=True,
                ),
                on_choice or self._on_existing_project_detected,
            )
        )

    def _on_existing_project_detected(self: _Shell, choice: str) -> None:
        """A checkout already carrying project metadata: name the new one, or reuse."""
        if choice == CHOICE_NEW_PROJECT:
            onboard_existing_project.clear_match(self.result)
            self._goto_slug()
            return
        self._after_existing_project_ready()

    def _goto_clone_existing_project_detected(self: _Shell) -> None:
        """Announce the match before the clone folder is chosen, not after."""
        self._goto_existing_project_ready(
            on_choice=self._on_clone_existing_project_detected,
        )

    def _on_clone_existing_project_detected(self: _Shell, choice: str) -> None:
        if choice == CHOICE_NEW_PROJECT:
            onboard_existing_project.clear_match(self.result)
        self._goto_clone_folder()


__all__ = [
    "CHOICE_CONNECT",
    "CHOICE_NEW_PROJECT",
    "DETECTED_ROWS",
    "ExistingProjectDetectedFlow",
]
