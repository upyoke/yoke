"""Answers and questions for the Apply progress, result and recovery screens."""

from __future__ import annotations

from yoke_cli.config.onboard_wizard_step_ids import STEP_FINISH
from yoke_cli.config.setup_prompt import TONE_ERROR, TONE_OK, SelectionRow, SetupPrompt

APPLYING_KEY = "review.applying"
APPLY_FAILED_KEY = "review.apply_failed"
APPLY_DIFFERENT_FOLDER_KEY = "review.different_folder"
APPLY_DONE_KEY = "review.done"
CONCEPTS_GUIDANCE = "Learn Yoke’s core words: https://upyoke.com/docs/start/concepts"
APPLY_FAILURE_GUIDANCE_LINE = (
    "Choose the first recovery action below that applies. Completed work and "
    "the durable report are preserved."
)

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
APPLY_FAILURE_DIFFERENT_FOLDER_ROW = SelectionRow(
    "different-folder",
    "Use a different folder",
    "preserve this partial checkout",
)

APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS = [
    SelectionRow(
        "confirm-different-folder",
        "Preserve checkout and go back",
        "choose a new empty folder next",
    ),
    SelectionRow("cancel", "Cancel", "back to recovery"),
]

APPLY_SUCCESS_ROWS = [
    SelectionRow("exit", "Exit", ""),
    SelectionRow("show-report", "Show report", "leave setup open"),
]


def apply_failure_rows(
    *,
    retryable: bool,
    can_resume: bool,
    can_use_different_folder: bool,
    has_details: bool = False,
    show_details: bool = False,
) -> list[SelectionRow]:
    base = list(APPLY_FAILURE_ROWS_RETRYABLE if retryable else APPLY_FAILURE_ROWS)
    insert_at = 1 if retryable else 0
    recovery: list[SelectionRow] = []
    if can_resume:
        recovery.append(APPLY_FAILURE_RESUME_ROW)
    if can_use_different_folder:
        recovery.append(APPLY_FAILURE_DIFFERENT_FOLDER_ROW)
    rows = base[:insert_at] + recovery + base[insert_at:]
    if has_details:
        rows.append(SelectionRow(
            "technical-details",
            "Hide technical details" if show_details else "Show technical details",
            "step id, report path, and resume command",
        ))
    return rows


def applying_prompt() -> SetupPrompt:
    return SetupPrompt(
        key=APPLYING_KEY,
        step=STEP_FINISH,
        title="Applying your setup.",
        message="Writing the reviewed plan.",
    )


def apply_failure_prompt(
    message: str,
    *,
    failed_step: str | None,
    report_path: str | None,
    resume_command: str | None,
    retryable: bool,
    can_resume: bool,
    can_use_different_folder: bool,
    show_details: bool,
) -> SetupPrompt:
    details = [APPLY_FAILURE_GUIDANCE_LINE]
    if failed_step:
        details.append(f"Failed step: {failed_step}")
    if report_path:
        details.append(f"Report: {report_path}")
    if resume_command:
        details.append(f"Resume: {resume_command}")
    return SetupPrompt(
        key=APPLY_FAILED_KEY,
        step=STEP_FINISH,
        title="Couldn't finish setup.",
        message=message,
        detail_lines=tuple(details),
        choices=tuple(apply_failure_rows(
            retryable=retryable,
            can_resume=can_resume,
            can_use_different_folder=can_use_different_folder,
            has_details=bool(failed_step or report_path or resume_command),
            show_details=show_details,
        )),
        tone=TONE_ERROR,
        guidance=(
            "Tell the person the cause. Answer resume to continue the same run "
            "when it is offered, retry for a transient failure, or back to "
            "change an answer."
        ),
    )


def apply_different_folder_prompt(
    *, report_path: str | None, checkout_path: str | None
) -> SetupPrompt:
    details = []
    if checkout_path:
        details.append(f"Checkout: {checkout_path}")
    if report_path:
        details.append(f"Report: {report_path}")
    return SetupPrompt(
        key=APPLY_DIFFERENT_FOLDER_KEY,
        step=STEP_FINISH,
        title="Use a different folder?",
        message="This leaves the local checkout untouched; choose a new empty "
        "folder next.",
        detail_lines=tuple(details),
        choices=tuple(APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS),
        tone=TONE_ERROR,
    )


def apply_success_prompt(report_path: str | None) -> SetupPrompt:
    return SetupPrompt(
        key=APPLY_DONE_KEY,
        step=STEP_FINISH,
        title="Setup complete.",
        message="Everything in the Review plan was applied.",
        detail_lines=((f"Report: {report_path}",) if report_path else ())
        + (CONCEPTS_GUIDANCE,),
        choices=tuple(APPLY_SUCCESS_ROWS),
        tone=TONE_OK,
    )


__all__ = [
    "APPLYING_KEY",
    "APPLY_DIFFERENT_FOLDER_CONFIRM_ROWS",
    "APPLY_DIFFERENT_FOLDER_KEY",
    "APPLY_DONE_KEY",
    "APPLY_FAILED_KEY",
    "APPLY_FAILURE_DIFFERENT_FOLDER_ROW",
    "APPLY_FAILURE_RESUME_ROW",
    "APPLY_FAILURE_ROWS",
    "APPLY_FAILURE_ROWS_RETRYABLE",
    "APPLY_SUCCESS_ROWS",
    "apply_different_folder_prompt",
    "apply_failure_prompt",
    "apply_failure_rows",
    "apply_success_prompt",
    "applying_prompt",
]
