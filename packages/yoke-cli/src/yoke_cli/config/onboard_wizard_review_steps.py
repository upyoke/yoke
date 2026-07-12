"""Review-screen rows and body composition for the onboarding wizard."""

from __future__ import annotations

from typing import Callable

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.onboard_wizard_plan_review import (
    _PLAN_GROUPS,
    classify_plan,
    render_reuse_summary,
    render_write_plan,
)
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow


CONFIRM_ROWS = [
    SelectionRow("apply", "Apply", "writes everything above"),
    SelectionRow("cancel", "Cancel", "nothing is saved"),
]
CONFIRM_ROWS_AFTER_GITHUB = [
    SelectionRow("apply", "Apply", "writes the remaining setup above"),
    SelectionRow(
        "cancel", "Cancel",
        "GitHub stays saved; use yoke github disconnect to remove it",
    ),
]
REVIEW_TITLE = f"Review what {BRAND} will save."
REVIEW_SUBTITLE = "Nothing is written until you choose Apply."
REVIEW_AFTER_GITHUB_SUBTITLE = (
    "Machine GitHub authorization is already saved; only the remaining setup "
    "writes wait for Apply. Use yoke github disconnect to remove the saved "
    "authorization."
)
REVIEW_BLOCKED_ROWS = [
    SelectionRow("back", "Back to fix that", "step back and correct it"),
    SelectionRow("cancel", "Quit", "nothing is saved"),
]
REVIEW_BLOCKED_ROWS_AFTER_GITHUB = [
    SelectionRow("back", "Back to fix that", "step back and correct it"),
    SelectionRow(
        "cancel", "Quit",
        "GitHub stays saved; use yoke github disconnect to remove it",
    ),
]
FINISH_EMPTY_ROWS = [SelectionRow("apply", "Finish", "")]


def finish_body(
    plan: dict,
    *,
    problems: list[str] | None,
    notes: list[str] | None,
    machine_github_saved: bool,
    heading: Callable[[str, str | None], list[Static]],
) -> list[Static]:
    grouped = classify_plan(plan)
    has_writes = any(grouped.get(key) for _label, _css, key in _PLAN_GROUPS)
    if not has_writes:
        widgets = heading(
            "You're connected.",
            "Nothing new to save — the selected setup is already in place.",
        )
        widgets.extend(render_reuse_summary(plan))
        if len(widgets) > 2:
            widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(SelectionList(FINISH_EMPTY_ROWS))
        return widgets
    if problems:
        widgets = [
            Static(
                "✗ A few things to fix before applying.",
                classes="onboard-title-error",
            ),
            Static("", classes="onboard-spacer"),
        ]
        widgets.extend(
            Static(f"  • {escape(line)}", classes="onboard-plan-line")
            for line in problems
        )
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(SelectionList(
            REVIEW_BLOCKED_ROWS_AFTER_GITHUB
            if machine_github_saved else REVIEW_BLOCKED_ROWS
        ))
        return widgets
    review_subtitle = (
        REVIEW_AFTER_GITHUB_SUBTITLE
        if machine_github_saved else REVIEW_SUBTITLE
    )
    widgets = heading(REVIEW_TITLE, review_subtitle)
    widgets.extend(render_write_plan(plan))
    reuse_widgets = render_reuse_summary(plan)
    if reuse_widgets:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.extend(reuse_widgets)
    for line in notes or []:
        widgets.append(Static(f"Note: {escape(line)}", classes="onboard-note"))
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.extend(heading(REVIEW_TITLE, review_subtitle))
    widgets.append(SelectionList(
        CONFIRM_ROWS_AFTER_GITHUB if machine_github_saved else CONFIRM_ROWS
    ))
    return widgets


__all__ = [
    "CONFIRM_ROWS",
    "FINISH_EMPTY_ROWS",
    "REVIEW_BLOCKED_ROWS",
    "REVIEW_SUBTITLE",
    "REVIEW_TITLE",
    "finish_body",
]
