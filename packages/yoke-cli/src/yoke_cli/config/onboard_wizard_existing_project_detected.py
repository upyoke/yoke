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
CHOICE_DETAILS = "details"

DETECTED_ROWS = [
    SelectionRow(
        CHOICE_CONNECT,
        "Connect to it",
        "reuse this project's board, issues, and settings",
    ),
    SelectionRow(
        CHOICE_DETAILS,
        "Review details",
        "IDs, environment, branch, prefix, and evidence",
    ),
    SelectionRow(
        CHOICE_NEW_PROJECT,
        "Set up a separate project instead",
        "ignore the match and create a new one",
    ),
]


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view) -> None: ...
    def _goto_existing_project_ready(
        self,
        *,
        on_choice: Callable[[str], None] | None = None,
    ) -> None: ...
    def _after_existing_project_ready(self) -> None: ...
    def _goto_project_details(self) -> None: ...
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

        self._existing_project_details = False
        self._existing_project_on_choice = (
            on_choice or self._on_existing_project_detected
        )
        self._goto(
            _View(
                STEP_PROJECT,
                self._existing_project_body,
                self._on_existing_project_choice,
            )
        )

    def _existing_project_body(self: _Shell) -> list:
        repo = (
            self.result.project_github_repo
            or self.result.project_checkout_origin_url
            or "none"
        )
        summary = [
            f"Primary match: {onboard_existing_project.match_summary(self.result)}",
            f"Repository: {repo}",
            f"Checkout: {self.result.project_checkout or 'chosen after this step'}",
            "Connecting preserves this project's board, items, settings, and history.",
        ]
        if getattr(self, "_existing_project_details", False):
            summary.extend(match_detail_lines(self.result))
        rows = list(DETECTED_ROWS)
        if getattr(self, "_existing_project_details", False):
            rows[1] = SelectionRow(CHOICE_DETAILS, "Hide details", "return to summary")
        return steps.verification_body(
            f"Existing project found: {self.result.project_name or self.result.project_slug}.",
            "Yoke matched this code to a project already in the selected universe.",
            summary,
            rows,
            ok=True,
        )

    def _on_existing_project_choice(self: _Shell, choice: str) -> None:
        if choice == CHOICE_DETAILS:
            self._existing_project_details = not self._existing_project_details
            self._render_current()
            return
        self._existing_project_on_choice(choice)

    def _on_existing_project_detected(self: _Shell, choice: str) -> None:
        """A checkout already carrying project metadata: name the new one, or reuse."""
        if choice == CHOICE_NEW_PROJECT:
            onboard_existing_project.clear_match(self.result)
            self._goto_project_details()
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
    "CHOICE_DETAILS",
    "DETECTED_ROWS",
    "ExistingProjectDetectedFlow",
]
