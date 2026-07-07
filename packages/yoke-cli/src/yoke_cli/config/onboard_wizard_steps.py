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
# Apply result screens live in a sibling module; re-export so steps.apply_* stays
# the single import surface for the flow and tests.
from yoke_cli.config.onboard_wizard_apply_steps import (  # noqa: F401
    APPLY_FAILURE_ROWS,
    APPLY_FAILURE_RESUME_ROW,
    APPLY_FAILURE_ROWS_RETRYABLE,
    APPLY_FAILURE_START_OVER_ROW,
    APPLY_START_OVER_CONFIRM_ROWS,
    APPLY_STATUS_GLYPHS,
    APPLY_SUCCESS_ROWS,
    apply_failure_body,
    apply_progress_body,
    apply_start_over_body,
    apply_step_line,
    apply_success_body,
)
from yoke_cli.config.onboard_wizard import PROJECT_GITHUB_REUSE_MACHINE
from yoke_cli.config.onboard_wizard_palette import ACCENT, BRAND
from yoke_cli.config.onboard_wizard_plan_review import (
    _PLAN_GROUPS,
    _friendly_line,  # noqa: F401 - re-exported for steps.* callers and tests
    classify_plan,
    render_reuse_summary,
    render_write_plan,
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
                 "Connect a token (PAT)", "paste a GitHub token"),
    SelectionRow(onboard_machine_github.CHOICE_SKIP,
                 "Skip for now", "connect later"),
    SelectionRow(onboard_machine_github.CHOICE_TOKEN_FILE,
                 "Read token from a file", "path on disk"),
]

TOKEN_SOURCE_ROWS = [
    SelectionRow("prompt", "Paste it now", "saved to ~/.yoke/secrets"),
    SelectionRow("file", "Read it from a file", "path on disk"),
]

VERIFY_OK_ROWS = [
    SelectionRow("continue", "Continue", ""),
]

VERIFY_RETRY_ROWS = [
    SelectionRow("retry", "Try again", "paste a different token"),
    SelectionRow("back", "Back", "choose a different option"),
]

PROBE_RETRY_ROWS = [
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose a different option"),
]

PROJECT_GITHUB_ROWS = [
    SelectionRow(PROJECT_GITHUB_REUSE_MACHINE,
                 onboard_github_copy.PROJECT_GITHUB_REUSE_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_REUSE_DESC),
    SelectionRow("store-token",
                 onboard_github_copy.PROJECT_GITHUB_STORE_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_STORE_DESC),
    SelectionRow("skip",
                 onboard_github_copy.PROJECT_GITHUB_SKIP_LABEL,
                 onboard_github_copy.PROJECT_GITHUB_SKIP_DESC),
]

# Same picker minus the reuse-machine row, shown when no machine token was
# connected. Without a machine token there is nothing to reuse, so offering
# the reuse-machine row would map to store-token with a None token and dead-end
# at apply — drop the row rather than offer an option that cannot succeed.
PROJECT_GITHUB_ROWS_NO_MACHINE = PROJECT_GITHUB_ROWS[1:]

CONFIRM_ROWS = [
    SelectionRow("apply", "Apply", "writes everything above"),
    SelectionRow("cancel", "Cancel", "nothing is saved"),
]
REVIEW_TITLE = f"Review what {BRAND} will save."
REVIEW_SUBTITLE = "Nothing is written until you choose Apply."

# Shown when the Review pre-flight found problems: Apply is withheld until they
# clear, so the only forward action is to step back and fix them (or quit).
REVIEW_BLOCKED_ROWS = [
    SelectionRow("back", "Back to fix that", "step back and correct it"),
    SelectionRow("cancel", "Quit", "nothing is saved"),
]

# Shown when the plan has no persistent writes — a single Finish row that still
# routes through the apply confirm so the wizard exits cleanly.
FINISH_EMPTY_ROWS = [
    SelectionRow("apply", "Finish", ""),
]

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
) -> list[Static]:
    grouped = classify_plan(plan)
    has_writes = any(grouped.get(key) for _label, _css, key in _PLAN_GROUPS)
    if not has_writes:
        widgets = _heading(
            "You're connected.",
            "Nothing new to save — the selected setup is already in place.",
        )
        widgets.extend(render_reuse_summary(plan))
        if len(widgets) > 2:
            widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(SelectionList(FINISH_EMPTY_ROWS))
        return widgets
    # Pre-flight found problems: show ALL of them at once and guard Apply behind a
    # single "Back to fix that" row, so a stale target / token / repo-name can't
    # be applied into a half-written state.
    if problems:
        widgets = [
            Static("✗ A few things to fix before applying.",
                   classes="onboard-title-error"),
            Static("", classes="onboard-spacer"),
        ]
        widgets.extend(
            Static(f"  • {escape(line)}", classes="onboard-plan-line")
            for line in problems
        )
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(SelectionList(REVIEW_BLOCKED_ROWS))
        return widgets
    widgets = _heading(REVIEW_TITLE, REVIEW_SUBTITLE)
    widgets.extend(render_write_plan(plan))
    reuse_widgets = render_reuse_summary(plan)
    if reuse_widgets:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.extend(reuse_widgets)
    # Advisory notes (e.g. an existing empty repo Apply will reuse) sit between
    # the plan and the Apply row so the user knows what "Apply" will really do.
    for line in notes or []:
        widgets.append(Static(f"Note: {escape(line)}", classes="onboard-note"))
    # Long plans can scroll the focused Apply row into view and push the top
    # heading off-screen. Repeat the safety copy next to the action rows so the
    # final consent screen still names what Apply means.
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.extend(_heading(REVIEW_TITLE, REVIEW_SUBTITLE))
    widgets.append(SelectionList(CONFIRM_ROWS))
    return widgets


def reset_project_fields(result: Any) -> None:
    result.project_remote_url = None
    result.project_checkout = None
    result.project_slug = None
    result.project_name = None
    result.project_github_repo = None
    result.project_default_branch = None
    result.project_public_item_prefix = None
    result.existing_project_id = None
    result.existing_project_match_source = None
    result.existing_project_local_source = None
    result.project_github_adoption = None
    result.project_github_token = None
    result.project_publish_to_github = False
    result.project_publish_owner = None
    result.project_publish_owner_login = None
    result.project_publish_repo_name = None
    result.project_publish_private = True
    result.project_clone_outcome = None
    result.project_clone_keep_upstream = True
    result.board_art_word = None
    result.board_art_seed = None
    result.board_art_variants = []


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
    "APPLY_FAILURE_START_OVER_ROW",
    "APPLY_START_OVER_CONFIRM_ROWS",
    "APPLY_STATUS_GLYPHS",
    "APPLY_SUCCESS_ROWS",
    "FINISH_EMPTY_ROWS",
    "MACHINE_GITHUB_ROWS",
    "MODE_ROWS",
    "PROJECT_GITHUB_ROWS",
    "PROJECT_GITHUB_ROWS_NO_MACHINE",
    "PROBE_RETRY_ROWS",
    "REVIEW_BLOCKED_ROWS",
    "REVIEW_SUBTITLE",
    "REVIEW_TITLE",
    "TOKEN_SOURCE_ROWS",
    "VERIFY_OK_ROWS",
    "VERIFY_RETRY_ROWS",
    "apply_failure_body",
    "apply_progress_body",
    "apply_start_over_body",
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
