"""Wizard bodies, rows, and helpers grouped by their final write scope."""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
from yoke_cli.config.onboard_wizard_project_fields import (
    reset_project_fields,
    reset_project_publish_fields,
    slug_from_checkout,
)

from yoke_cli.config.onboard_wizard_apply_prompts import (  # noqa: F401
    APPLY_FAILURE_ROWS,
    APPLY_FAILURE_RESUME_ROW,
    APPLY_FAILURE_ROWS_RETRYABLE,
    APPLY_FAILURE_DIFFERENT_FOLDER_ROW,
    APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS,
    APPLY_SUCCESS_ROWS,
)
from yoke_cli.config.onboard_wizard_apply_steps import (  # noqa: F401
    APPLY_STATUS_GLYPHS,
    apply_failure_body,
    apply_progress_body,
    apply_progress_lines,
    apply_different_folder_body,
    apply_step_group,
    apply_step_line,
    apply_success_body,
    apply_success_body_from_report,
)
from yoke_cli.config.onboard_wizard import PROJECT_GITHUB_REUSE_MACHINE
from yoke_cli.config.onboard_wizard_plan_review import (
    _friendly_line,  # noqa: F401 - re-exported for steps.* callers and tests
    classify_plan,
    render_reuse_summary,
    render_write_plan,
)
from yoke_cli.config import onboard_wizard_review_steps as review_steps
from yoke_cli.config.onboard_wizard_review_steps import (
    CONFIRM_ROWS,
    FINISH_EMPTY_ROWS,
    REVIEW_BLOCKED_ROWS,
    REVIEW_SUBTITLE,
    REVIEW_TITLE,
)
from yoke_cli.config.setup_prompt import SelectionRow
from yoke_cli.config.setup_prompt_render import heading


def _github_skip_row(value: str) -> SelectionRow:
    return SelectionRow(
        value,
        onboard_github_copy.MACHINE_GITHUB_SKIP_LABEL,
        onboard_github_copy.MACHINE_GITHUB_SKIP_DESC,
    )


MODE_ROWS = [
    SelectionRow(
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "Existing folder on my machine",
        "git repo or not",
    ),
    SelectionRow(
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
        onboard_github_copy.CLONE_FROM_GITHUB_LABEL,
        onboard_github_copy.CLONE_FROM_GITHUB_DESC,
    ),
    SelectionRow(
        onboard_project.PROJECT_MODE_CREATE_REPO,
        "Create a new project",
        "new folder, optionally also created on GitHub",
    ),
    SelectionRow(
        onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
        "Edit Yoke source",
        "use a checkout or clone any fork · dogfood or contribute",
    ),
    SelectionRow(
        onboard_project.PROJECT_MODE_MACHINE_ONLY,
        "Don't set up a project now",
        "just the machine",
    ),
]

MACHINE_GITHUB_ROWS = [
    SelectionRow(
        onboard_machine_github.CHOICE_CONNECT,
        "Connect GitHub",
        "open the Yoke GitHub App flow",
    ),
    _github_skip_row(onboard_machine_github.CHOICE_SKIP),
]

VERIFY_OK_ROWS = [SelectionRow("continue", "Continue", "")]
HOSTED_MACHINE_RETRY_ROWS = [
    SelectionRow("retry", "Try again", "start a fresh browser sign-in"),
    SelectionRow("back", "Back", "choose a different option"),
]
PROBE_RETRY_ROWS = [
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose a different option"),
]

GITHUB_APP_UNAVAILABLE_ROWS = [
    SelectionRow("reconnect", "Reconnect GitHub", "replace saved authorization"),
    _github_skip_row("backlog"),
    SelectionRow("back", "Back", "choose a different option"),
]

GITHUB_APP_PENDING_ROWS = [
    SelectionRow("check", "Check access", "after finishing in GitHub"),
    _github_skip_row("backlog"),
    SelectionRow("back", "Back", "choose a different option"),
]

PROJECT_GITHUB_ACCESS_ROWS = [
    SelectionRow("refresh", "Check access", "after updating the App in GitHub"),
    _github_skip_row("backlog"),
    SelectionRow("back", "Back", "choose a different option"),
]

PRIVATE_REPO_EMPTY_ROWS = [
    SelectionRow(
        "manage",
        "Manage repository access in GitHub",
        "choose private repos",
    ),
    SelectionRow("check", "Check again", "refresh authorized repositories"),
    SelectionRow("back", "Back", "choose public or private"),
]

PROJECT_GITHUB_ROWS = [
    SelectionRow(
        PROJECT_GITHUB_REUSE_MACHINE,
        onboard_github_copy.PROJECT_GITHUB_REUSE_LABEL,
        onboard_github_copy.PROJECT_GITHUB_REUSE_DESC,
    ),
    SelectionRow(
        GITHUB_ADOPTION_APP_BINDING,
        onboard_github_copy.PROJECT_GITHUB_STORE_LABEL,
        onboard_github_copy.PROJECT_GITHUB_STORE_DESC,
    ),
    SelectionRow(
        "skip",
        onboard_github_copy.PROJECT_GITHUB_SKIP_LABEL,
        onboard_github_copy.PROJECT_GITHUB_SKIP_DESC,
    ),
]

PROJECT_GITHUB_ROWS_NO_MACHINE = [PROJECT_GITHUB_ROWS[-1]]


def error_body(message: str) -> list[Static]:
    return [
        Static("✗ Couldn't build your setup plan.", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(f"Cause: {escape(message)}", classes="onboard-plan-line"),
        Static("What to do", classes="onboard-title"),
        Static(
            "Press Esc, correct the affected answer, then return to Review.",
            classes="onboard-plan-line",
        ),
    ]


def finish_body(
    plan: dict[str, Any],
    *,
    problems: list[str] | None = None,
    notes: list[str] | None = None,
    machine_github_saved: bool = False,
    show_all: bool = False,
    status_lines: list[str] | None = None,
) -> list[Static]:
    return review_steps.finish_body(
        plan,
        problems=problems,
        notes=notes,
        machine_github_saved=machine_github_saved,
        show_all=show_all,
        status_lines=status_lines,
        heading=heading,
    )


__all__ = [
    "CONFIRM_ROWS",
    "APPLY_FAILURE_ROWS",
    "APPLY_FAILURE_RESUME_ROW",
    "APPLY_FAILURE_ROWS_RETRYABLE",
    "APPLY_FAILURE_DIFFERENT_FOLDER_ROW",
    "APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS",
    "APPLY_STATUS_GLYPHS",
    "APPLY_SUCCESS_ROWS",
    "FINISH_EMPTY_ROWS",
    "GITHUB_APP_UNAVAILABLE_ROWS",
    "GITHUB_APP_PENDING_ROWS",
    "MACHINE_GITHUB_ROWS",
    "PROJECT_GITHUB_ACCESS_ROWS",
    "PRIVATE_REPO_EMPTY_ROWS",
    "MODE_ROWS",
    "PROJECT_GITHUB_ROWS",
    "PROJECT_GITHUB_ROWS_NO_MACHINE",
    "PROBE_RETRY_ROWS",
    "REVIEW_BLOCKED_ROWS",
    "REVIEW_SUBTITLE",
    "REVIEW_TITLE",
    "VERIFY_OK_ROWS",
    "HOSTED_MACHINE_RETRY_ROWS",
    "apply_failure_body",
    "apply_progress_body",
    "apply_different_folder_body",
    "apply_step_line",
    "apply_success_body",
    "apply_success_body_from_report",
    "classify_plan",
    "error_body",
    "finish_body",
    "render_write_plan",
    "render_reuse_summary",
    "reset_project_fields",
    "reset_project_publish_fields",
    "slug_from_checkout",
]
