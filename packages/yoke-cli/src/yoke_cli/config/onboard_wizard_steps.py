"""Body builders, option rows, and pure helpers for the onboarding wizard.

Each ``*_body`` returns the list of widgets a step mounts into the redraw-in-
place body container. The row constants are the arrow-key option sets; the
classifier buckets ``build_report``'s write-plan steps into machine /
Yoke-core-database / repo-local / source-dev-admin groups for the Finish
preview.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
# Apply result screens live in a sibling module; re-export so steps.apply_* stays
# the single import surface for the flow and tests.
from yoke_cli.config.onboard_wizard_apply_steps import (  # noqa: F401
    APPLY_FAILURE_ROWS,
    APPLY_FAILURE_RESUME_ROW,
    APPLY_FAILURE_ROWS_RETRYABLE,
    APPLY_FAILURE_DIFFERENT_FOLDER_ROW,
    APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS,
    APPLY_STATUS_GLYPHS,
    APPLY_SUCCESS_ROWS,
    apply_failure_body,
    apply_progress_body,
    apply_different_folder_body,
    apply_step_line,
    apply_success_body,
)
from yoke_cli.config.onboard_wizard import PROJECT_GITHUB_REUSE_MACHINE
from yoke_cli.config.onboard_wizard_palette import ACCENT
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
from yoke_cli.config.onboard_wizard_widgets import (
    FocusInput,
    SelectionList,
    SelectionRow,
)

MODE_ROWS = [
    SelectionRow(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
                 "Existing folder on my machine", "git repo or not"),
    SelectionRow(onboard_project.PROJECT_MODE_CLONE_REMOTE,
                 "Clone a project from GitHub", "into a new folder"),
    SelectionRow(onboard_project.PROJECT_MODE_CREATE_REPO,
                 "Create a new project", "new folder, optionally also created on GitHub"),
    SelectionRow(onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
                 "Develop Yoke itself", "advanced · contributors"),
    SelectionRow(onboard_project.PROJECT_MODE_MACHINE_ONLY,
                 "Don't set up a project now", "just the machine"),
]

MACHINE_GITHUB_ROWS = [
    SelectionRow(onboard_machine_github.CHOICE_CONNECT,
                 "Connect GitHub", "open the Yoke GitHub App flow"),
    SelectionRow(onboard_machine_github.CHOICE_SKIP,
                 "Use backlog only", "connect later"),
]

YOKE_TOKEN_SOURCE_ROWS = [
    SelectionRow("prompt", "Paste it now", "saved to ~/.yoke/secrets"),
    SelectionRow("file", "Read it from a file", "path on disk"),
]

VERIFY_OK_ROWS = [
    SelectionRow("continue", "Continue", ""),
]

YOKE_TOKEN_VERIFY_RETRY_ROWS = [
    SelectionRow("retry", "Try again", "paste a different token"),
    SelectionRow("back", "Back", "choose a different option"),
]

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
    SelectionRow("backlog", "Use backlog only", "continue without GitHub"),
    SelectionRow("back", "Back", "choose a different option"),
]

GITHUB_APP_PENDING_ROWS = [
    SelectionRow("check", "Check access", "after finishing in GitHub"),
    SelectionRow("backlog", "Use backlog only", "continue without GitHub"),
    SelectionRow("back", "Back", "choose a different option"),
]

PROJECT_GITHUB_ACCESS_ROWS = [
    SelectionRow("refresh", "Check access", "after updating the App in GitHub"),
    SelectionRow("backlog", "Use backlog only", "continue without GitHub"),
    SelectionRow("back", "Back", "choose a different option"),
]

PRIVATE_REPO_EMPTY_ROWS = [
    SelectionRow(
        "manage", "Manage repository access in GitHub", "choose private repos",
    ),
    SelectionRow("check", "Check again", "refresh authorized repositories"),
    SelectionRow("back", "Back", "choose public or private"),
]

PROJECT_GITHUB_ROWS = [
    SelectionRow(PROJECT_GITHUB_REUSE_MACHINE, onboard_github_copy.PROJECT_GITHUB_REUSE_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_REUSE_DESC),
    SelectionRow(GITHUB_ADOPTION_APP_BINDING, onboard_github_copy.PROJECT_GITHUB_STORE_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_STORE_DESC),
    SelectionRow("skip", onboard_github_copy.PROJECT_GITHUB_SKIP_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_SKIP_DESC),
]

PROJECT_GITHUB_ROWS_NO_MACHINE = [PROJECT_GITHUB_ROWS[-1]]
def _heading(title: str, subtitle: str | None) -> list[Static]:
    widgets = [Static(title, classes="onboard-title")]
    if subtitle is not None:
        widgets.append(Static(subtitle, classes="onboard-subtitle"))
    widgets.append(Static("", classes="onboard-spacer"))
    return widgets


def selection_body(
    title: str, subtitle: str | None, rows: list[SelectionRow], *, initial: int = 0,
) -> list[Static]:
    return [*_heading(title, subtitle), SelectionList(rows, initial=initial)]


def input_body(
    title: str,
    subtitle: str,
    placeholder: str,
    password: bool,
    *,
    initial_value: str = "",
) -> list[Static]:
    return [
        *_heading(title, subtitle),
        FocusInput(
            value=initial_value,
            placeholder=placeholder,
            password=password,
            id="onboard-input",
        ),
        Static("", classes="onboard-input-error"),
    ]


def checking_body(
    title: str,
    message: str,
    detail_lines: list[str] | None = None,
) -> list[Static]:
    widgets = [
        Static(title, classes="onboard-title"),
        Static("", classes="onboard-spacer"),
        Static(escape(message), classes="onboard-plan-line"),
    ]
    widgets.extend(
        Static(f"  • {escape(line)}", classes="onboard-plan-line")
        for line in detail_lines or []
    )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(Static("Checking...", classes="onboard-note"))
    return widgets


def project_mode_body() -> list[Static]:
    return selection_body(
        "Set up a project.",
        "Where's the code? You can change this later.",
        MODE_ROWS,
    )


def error_body(message: str) -> list[Static]:
    return [
        Static("✗ Couldn't build your setup plan.", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(escape(message), classes="onboard-plan-line"),
        Static("", classes="onboard-spacer"),
        Static("Press esc to go back and fix that answer.", classes="onboard-note"),
    ]


def verification_body(
    title: str,
    message: str,
    detail_lines: list[str],
    rows: list[SelectionRow],
    *,
    ok: bool,
) -> list[Static]:
    # One error convention everywhere: a bold red ✗ title, with the explanatory
    # detail in calm neutral text (not red). Success keeps a plain title and a
    # green message.
    if ok:
        widgets = [
            Static(title, classes="onboard-title"),
            Static("", classes="onboard-spacer"),
            Static(f"[{ACCENT}]{escape(message)}[/]", classes="onboard-plan-line"),
        ]
    else:
        widgets = [
            Static(f"✗ {escape(title)}", classes="onboard-title-error"),
            Static("", classes="onboard-spacer"),
            Static(escape(message), classes="onboard-plan-line"),
        ]
    widgets.extend(
        Static(f"  • {escape(line)}", classes="onboard-plan-line")
        for line in detail_lines
    )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(rows))
    return widgets


def finish_body(
    plan: dict[str, Any], *, problems: list[str] | None = None,
    notes: list[str] | None = None,
    machine_github_saved: bool = False,
) -> list[Static]:
    return review_steps.finish_body(
        plan,
        problems=problems,
        notes=notes,
        machine_github_saved=machine_github_saved,
        heading=_heading,
    )


def reset_project_fields(result: Any) -> None:
    result.project_remote_url = None
    result.project_checkout = None
    result.project_slug = None
    result.project_name = None
    result.project_github_repo = None
    result.project_github_repository_id = None
    result.project_github_installation_id = None
    result.project_checkout_origin_url = None
    result.project_checkout_github_repo = None
    result.project_default_branch = None
    result.project_public_item_prefix = None
    result.existing_project_id = None
    result.existing_project_match_source = None
    result.existing_project_local_source = None
    result.project_github_adoption = None
    result.project_github_adoption_preserve = False
    reset_project_publish_fields(result)
    result.project_clone_outcome = None
    result.project_clone_keep_upstream = True
    result.project_clone_requires_machine_github = False
    result.project_source_default_branch = None
    result.project_keep_existing_remote = False
    result.board_art_word = None
    result.board_art_seed = None
    result.board_art_variants = []


def reset_project_publish_fields(result: Any) -> None:
    """Clear every create/manual-attach field as one navigation transaction."""

    result.project_publish_to_github = False
    result.project_publish_owner = None
    result.project_publish_owner_login = None
    result.project_publish_repo_name = None
    result.project_publish_private = True
    result.project_publish_create_repository = True
    result.project_publish_repository_id = None
    result.project_publish_installation_id = None


def slug_from_checkout(checkout: str | None) -> str:
    if not checkout:
        return "project"
    value = checkout.rstrip("/").split("/")[-1].strip().lower()
    cleaned = "".join(c if c.isalnum() or c == "-" else "-" for c in value)
    return "-".join(p for p in cleaned.split("-") if p) or "project"


def prefix_from_slug(slug: str | None) -> str:
    letters = [c for c in (slug or "").upper() if c.isalnum()]
    return "".join(letters[:4]) or "PROJ"


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
    "YOKE_TOKEN_SOURCE_ROWS",
    "VERIFY_OK_ROWS",
    "YOKE_TOKEN_VERIFY_RETRY_ROWS",
    "HOSTED_MACHINE_RETRY_ROWS",
    "apply_failure_body",
    "apply_progress_body",
    "apply_different_folder_body",
    "apply_step_line",
    "apply_success_body",
    "classify_plan",
    "checking_body",
    "error_body",
    "finish_body",
    "input_body",
    "prefix_from_slug",
    "project_mode_body",
    "render_write_plan",
    "render_reuse_summary",
    "reset_project_fields",
    "selection_body",
    "slug_from_checkout",
    "verification_body",
]
