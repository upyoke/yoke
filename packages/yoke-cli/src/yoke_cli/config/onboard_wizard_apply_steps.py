"""Body builders and option rows for the apply result screens.

The Applying / success / failure screens are the terminal states of the Review
step: ``apply_progress_body`` is the live screen the worker updates row-by-row,
``apply_success_body`` / ``apply_failure_body`` are the outcomes. Kept apart from
:mod:`onboard_wizard_steps` (the input/review builders) so each stays small;
``onboard_wizard_steps`` re-exports these so ``steps.apply_*`` callers are stable.
"""

from __future__ import annotations

from typing import Any, Sequence

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import onboard_global_skill
from yoke_cli.config import onboard_hook_resident
from yoke_cli.config import onboard_machine_registry
from yoke_cli.config.onboard_terminal import RICH_GLYPHS, glyphs
from yoke_cli.config import onboard_session_relay
from yoke_cli.config.onboard_wizard_plan_review import (
    _CORE_ACTIONS,
    _MACHINE_ACTIONS,
    _REPO_ACTIONS,
)
from yoke_cli.config.onboard_wizard_widgets import SelectionList
from yoke_cli.config.onboard_wizard_apply_prompts import (
    APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS,
    APPLY_FAILURE_GUIDANCE_LINE,
    APPLY_SUCCESS_ROWS,
    apply_failure_rows,
)
from yoke_cli.project_install import hook_trust_report

APPLY_STATUS_GLYPHS = {
    "pending": RICH_GLYPHS.apply_pending,
    "running": RICH_GLYPHS.apply_running,
    "done": RICH_GLYPHS.apply_done,
    "skipped": RICH_GLYPHS.apply_skipped,
    "failed": RICH_GLYPHS.apply_failed,
    "incomplete": RICH_GLYPHS.apply_failed,
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
        "incomplete": marks.apply_failed,
    }.get(status, marks.apply_pending)
    return f"  {glyph} {escape(str(step.get('label', '')))}"


def apply_step_group(action: str) -> str:
    from yoke_cli.config.onboard_machine_setup import BROWSER_SETUP_ACTION

    if action == BROWSER_SETUP_ACTION:
        return "machine"
    if action in _MACHINE_ACTIONS:
        return "machine"
    if action in _REPO_ACTIONS:
        return "project"
    if action in _CORE_ACTIONS:
        return "core"
    return "source" if "source" in action else "core"


def apply_progress_lines(steps: list[dict[str, Any]]) -> dict[str, str]:
    done_states = {"done", "skipped"}
    completed = sum(step.get("status") in done_states for step in steps)
    current = next(
        (
            str(step.get("label") or "")
            for step in steps
            if step.get("status") == "running"
        ),
        "Waiting for the next operation…"
        if completed < len(steps)
        else "Finalizing report…",
    )
    lines = {
        "overall": f"Overall: {completed} of {len(steps)} complete",
        "current": f"Current: {current}",
    }
    for key, label in (
        ("machine", "Machine"),
        ("core", "Core"),
        ("project", "Project"),
        ("source", "Source"),
    ):
        group = [step for step in steps if step.get("group") == key]
        if group:
            finished = sum(step.get("status") in done_states for step in group)
            lines[key] = f"  {label}: {finished}/{len(group)}"
    return lines


def apply_progress_body(steps: list[dict[str, Any]]) -> list[Static]:
    """Live totals and one status row per reviewed operation."""
    lines = apply_progress_lines(steps)
    widgets: list[Static] = [
        Static("Applying your setup.", classes="onboard-title"),
        Static("", classes="onboard-spacer"),
        Static(lines["overall"], id="apply-overall", classes="onboard-plan-line"),
    ]
    for key in ("machine", "core", "project", "source"):
        if key in lines:
            widgets.append(
                Static(lines[key], id=f"apply-group-{key}", classes="onboard-plan-line")
            )
    widgets.extend(
        [
            Static("", classes="onboard-spacer"),
            Static(lines["current"], id="apply-current", classes="onboard-plan-line"),
        ]
    )
    widgets.extend(
        Static(
            apply_step_line(step), id=f"apply-step-{index}", classes="onboard-plan-line"
        )
        for index, step in enumerate(steps)
    )
    return widgets


def apply_failure_body(
    message: str,
    *,
    failed_step: str | None,
    report_path: str | None,
    resume_command: str | None,
    retryable: bool = False,
    can_resume: bool = False,
    can_use_different_folder: bool = False,
    show_details: bool = False,
) -> list[Static]:
    widgets = [
        Static("✗ Couldn't finish setup.", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(f"Cause: {escape(message)}", classes="onboard-plan-line"),
        Static("What to do", classes="onboard-title"),
        Static(APPLY_FAILURE_GUIDANCE_LINE, classes="onboard-plan-line"),
    ]
    if show_details and failed_step:
        widgets.append(
            Static(f"Failed step: {escape(failed_step)}", classes="onboard-note")
        )
    if show_details and report_path:
        widgets.append(
            Static(f"Report: {escape(report_path)}", classes="onboard-plan-line")
        )
    if show_details and resume_command:
        widgets.append(
            Static(f"Resume: {escape(resume_command)}", classes="onboard-note")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = apply_failure_rows(
        retryable=retryable,
        can_resume=can_resume,
        can_use_different_folder=can_use_different_folder,
        has_details=bool(failed_step or report_path or resume_command),
        show_details=show_details,
    )
    widgets.append(SelectionList(rows))
    return widgets


def apply_different_folder_body(
    *,
    report_path: str | None,
    checkout_path: str | None,
) -> list[Static]:
    widgets = [
        Static("Use a different folder?", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(
            "This leaves the local checkout untouched; choose a new empty folder next.",
            classes="onboard-plan-line",
        ),
    ]
    if checkout_path:
        widgets.append(
            Static(f"Checkout: {escape(checkout_path)}", classes="onboard-plan-line")
        )
    if report_path:
        widgets.append(Static(f"Report: {escape(report_path)}", classes="onboard-note"))
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS))
    return widgets


BOARD_ART_COMMITTED_LINE = "✓ Board art committed and board rebuilt"


def apply_success_body_from_report(
    report_path: str | None,
    report: Any,
    *,
    board_art_committed: bool = False,
) -> list[Static]:
    """The success screen for one applied report, reading what it recorded.

    Board art is the one thing the report cannot carry: this run commits it
    after the report is written, so the caller passes that outcome in.
    """
    report = report if isinstance(report, dict) else {}
    project_report = report.get("project_onboarding")
    relay = report.get("session_relay")
    return apply_success_body(
        report_path,
        hook_trust_report.report_lines(
            project_report.get("install") if isinstance(project_report, dict) else None
        ),
        relay_lines=onboard_session_relay.report_complete_lines(relay),
        registry_lines=onboard_machine_registry.summary_lines(
            report.get("machine_registry")
        )
        + onboard_global_skill.summary_lines(report.get("global_skill"))
        + onboard_hook_resident.summary_lines(report.get("hook_evaluator")),
        board_art_committed=board_art_committed,
    )


def apply_success_body(
    report_path: str | None,
    hook_trust: Sequence[str] = (),
    *,
    relay_lines: Sequence[str] = (),
    registry_lines: Sequence[str] = (),
    board_art_committed: bool = False,
) -> list[Static]:
    widgets = [
        Static("✓ Setup complete.", classes="onboard-title"),
        Static("", classes="onboard-spacer"),
        Static(
            "Everything in the Review plan was applied.",
            classes="onboard-plan-line",
        ),
    ]
    if board_art_committed:
        widgets.append(
            Static(
                "✓ Progress map and ASCII, Emoji, Mixed headers ready",
                classes="onboard-plan-line",
            )
        )
        widgets.append(
            Static(
                "Customize later: yoke board art variant create --help",
                classes="onboard-plan-line",
            )
        )
    if relay_lines:
        widgets.append(Static("✓ Session relay ready", classes="onboard-plan-line"))
    # A machine that connected is set up whatever the registry decided, so a
    # refusal is named here with its recovery instead of failing the apply.
    for line in registry_lines:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(Static(escape(line), classes="onboard-plan-line"))
    # The one step the wizard wrote glue for but cannot perform itself.
    for teaching in hook_trust:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(Static(escape(teaching), classes="onboard-plan-line"))
    if report_path:
        widgets.append(Static("", classes="onboard-spacer"))
        widgets.append(
            Static(f"Report: {escape(report_path)}", classes="onboard-plan-line")
        )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(APPLY_SUCCESS_ROWS))
    return widgets


__all__ = [
    "BOARD_ART_COMMITTED_LINE",
    "APPLY_STATUS_GLYPHS",
    "apply_failure_body",
    "apply_progress_body",
    "apply_different_folder_body",
    "apply_step_line",
    "apply_success_body",
    "apply_success_body_from_report",
]
