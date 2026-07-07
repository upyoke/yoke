"""Body builders and option rows for the apply result screens.

The Applying / success / failure screens are the terminal states of the Review
step: ``apply_progress_body`` is the live screen the worker updates row-by-row,
``apply_success_body`` / ``apply_failure_body`` are the outcomes. Kept apart from
:mod:`onboard_wizard_steps` (the input/review builders) so each stays small;
``onboard_wizard_steps`` re-exports these so ``steps.apply_*`` callers are stable.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config.onboard_terminal import RICH_GLYPHS, glyphs
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

APPLY_FAILURE_ROWS = [
    SelectionRow("back", "Change answers", "go back and adjust setup"),
    SelectionRow("exit", "Exit", "leave report on disk"),
]

# Offered when re-running the same apply could plausibly succeed (transient /
# network / TOCTOU). A repo name that already exists with content is excluded —
# retrying the same name just fails again — so that case uses APPLY_FAILURE_ROWS.
APPLY_FAILURE_ROWS_RETRYABLE = [
    SelectionRow("retry", "Try again", "re-run apply"),
    SelectionRow("back", "Change answers", "go back and adjust setup"),
    SelectionRow("exit", "Exit", "leave report on disk"),
]

APPLY_FAILURE_RESUME_ROW = SelectionRow(
    "resume",
    "Resume from cloned folder",
    "keep completed work",
)
APPLY_FAILURE_START_OVER_ROW = SelectionRow(
    "start-over",
    "Start over",
    "remove local checkout",
)

APPLY_START_OVER_CONFIRM_ROWS = [
    SelectionRow(
        "confirm-start-over",
        "Remove checkout",
        "delete the local folder",
    ),
    SelectionRow("cancel", "Cancel", "back to recovery"),
]

APPLY_SUCCESS_ROWS = [
    SelectionRow("exit", "Exit", ""),
    SelectionRow("show-report", "Show report", "leave setup open"),
]

APPLY_STATUS_GLYPHS = {
    "pending": RICH_GLYPHS.apply_pending,
    "running": RICH_GLYPHS.apply_running,
    "done": RICH_GLYPHS.apply_done,
    "skipped": RICH_GLYPHS.apply_skipped,
    "failed": RICH_GLYPHS.apply_failed,
}


def apply_step_line(step: dict[str, Any]) -> str:
    """One Applying-screen row: status glyph + the step's friendly label."""
    marks = glyphs()
    status = str(step.get("status"))
    glyph = {
        "pending": marks.apply_pending,
        "running": marks.apply_running,
        "done": marks.apply_done,
        "skipped": marks.apply_skipped,
        "failed": marks.apply_failed,
    }.get(status, marks.apply_pending)
    return f"  {glyph} {escape(str(step.get('label', '')))}"


def apply_progress_body(steps: list[dict[str, Any]]) -> list[Static]:
    """Live 'Applying...' screen: one row per plan step with a status glyph.

    Each row carries a stable id (``applystep-<step_id>``) so the apply worker
    can flip a single row pending -> running -> done/skipped/failed in place
    without re-mounting the whole body.
    """
    widgets: list[Static] = [
        Static("Applying your setup.", classes="onboard-title"),
        Static("", classes="onboard-spacer"),
    ]
    for step in steps:
        widgets.append(Static(
            apply_step_line(step),
            id=f"applystep-{step['step_id']}",
            classes="onboard-plan-line",
        ))
    return widgets


def apply_failure_body(
    message: str,
    *,
    failed_step: str | None,
    report_path: str | None,
    resume_command: str | None,
    retryable: bool = False,
    can_resume: bool = False,
    can_start_over: bool = False,
) -> list[Static]:
    widgets = [
        Static("✗ Couldn't finish setup.", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(escape(message), classes="onboard-plan-line"),
    ]
    if failed_step:
        widgets.append(
            Static(f"Failed step: {escape(failed_step)}", classes="onboard-note")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    if report_path:
        widgets.append(
            Static(f"Report: {escape(report_path)}", classes="onboard-plan-line")
        )
    if resume_command:
        widgets.append(
            Static(f"Resume: {escape(resume_command)}", classes="onboard-note")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = _apply_failure_rows(
        retryable=retryable,
        can_resume=can_resume,
        can_start_over=can_start_over,
    )
    widgets.append(SelectionList(rows))
    return widgets


def apply_start_over_body(
    *,
    report_path: str | None,
    checkout_path: str | None,
) -> list[Static]:
    widgets = [
        Static("Start over?", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(
            "This removes the local checkout Yoke created for this run.",
            classes="onboard-plan-line",
        ),
    ]
    if checkout_path:
        widgets.append(
            Static(f"Checkout: {escape(checkout_path)}", classes="onboard-plan-line")
        )
    if report_path:
        widgets.append(
            Static(f"Report: {escape(report_path)}", classes="onboard-note")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(APPLY_START_OVER_CONFIRM_ROWS))
    return widgets


def apply_success_body(report_path: str | None) -> list[Static]:
    widgets = [
        Static("✓ Setup complete.", classes="onboard-title"),
        Static("", classes="onboard-spacer"),
        Static(
            "Everything in the Review plan was applied.",
            classes="onboard-plan-line",
        ),
    ]
    if report_path:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(
            Static(f"Report: {escape(report_path)}", classes="onboard-plan-line")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(APPLY_SUCCESS_ROWS))
    return widgets


def _apply_failure_rows(
    *,
    retryable: bool,
    can_resume: bool,
    can_start_over: bool,
) -> list[SelectionRow]:
    base = list(APPLY_FAILURE_ROWS_RETRYABLE if retryable else APPLY_FAILURE_ROWS)
    insert_at = 1 if retryable else 0
    recovery: list[SelectionRow] = []
    if can_resume:
        recovery.append(APPLY_FAILURE_RESUME_ROW)
    if can_start_over:
        recovery.append(APPLY_FAILURE_START_OVER_ROW)
    return base[:insert_at] + recovery + base[insert_at:]


__all__ = [
    "APPLY_FAILURE_ROWS",
    "APPLY_FAILURE_RESUME_ROW",
    "APPLY_FAILURE_ROWS_RETRYABLE",
    "APPLY_FAILURE_START_OVER_ROW",
    "APPLY_START_OVER_CONFIRM_ROWS",
    "APPLY_STATUS_GLYPHS",
    "APPLY_SUCCESS_ROWS",
    "apply_failure_body",
    "apply_progress_body",
    "apply_start_over_body",
    "apply_step_line",
    "apply_success_body",
]
