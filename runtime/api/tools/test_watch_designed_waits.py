"""A deploy run parked at scoped QA reads as a wait, not an undiagnosed failure."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.deploy_pipeline import EXIT_AWAITING_QA
from yoke_core.domain.deployment_run_completion_preconditions import (
    awaiting_qa_report_lines,
    held_stage_report_lines,
)
from yoke_core.tools._watch_designed_waits import designed_wait
from yoke_core.tools._watch_terminal_outcome import format_terminal_outcome


RUN_ID = "run-20260929-004"
OBLIGATION = "item-qa YOK-1 browser case pending"


def _capture(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "raw.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_stages_complete_awaiting_qa_is_a_wait_naming_its_continuation(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, awaiting_qa_report_lines(RUN_ID, [OBLIGATION]))

    outcome = format_terminal_outcome(
        kind="deploy", exit_code=EXIT_AWAITING_QA, raw_capture=capture
    )

    assert "outcome: waiting" in outcome
    assert "failure" not in outcome
    assert "terminal cause not diagnosed" not in outcome
    assert "blocking QA unresolved" in outcome
    assert f"yoke deployment-runs get {RUN_ID}" in outcome
    assert "yoke deployment-runs remove-item --help" in outcome


def test_a_final_stage_held_before_it_ran_is_the_same_wait(tmp_path: Path) -> None:
    capture = _capture(
        tmp_path, held_stage_report_lines(RUN_ID, "hosted-release", [OBLIGATION])
    )

    outcome = format_terminal_outcome(
        kind="deploy", exit_code=EXIT_AWAITING_QA, raw_capture=capture
    )

    assert "outcome: waiting" in outcome
    assert "final stage held" in outcome
    assert f"yoke deployment-runs get {RUN_ID}" in outcome
    assert "yoke deployment-runs remove-item --help" in outcome


def test_a_resume_refused_for_skipping_qa_stays_a_failure(tmp_path: Path) -> None:
    """The refusal shares the exit code; only the hold's report makes a wait."""
    capture = _capture(
        tmp_path,
        ["Error: resume cannot skip required scoped QA: item-qa is unsettled"],
    )

    outcome = format_terminal_outcome(
        kind="deploy", exit_code=EXIT_AWAITING_QA, raw_capture=capture
    )

    assert "outcome: waiting" not in outcome
    assert "failure: Error: resume cannot skip required scoped QA" in outcome


def test_another_watch_kind_at_the_same_exit_code_is_not_a_wait(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, awaiting_qa_report_lines(RUN_ID, [OBLIGATION]))

    assert (
        designed_wait(kind="merge", exit_code=EXIT_AWAITING_QA, raw_capture=capture)
        is None
    )


def test_a_deploy_failure_exit_is_never_read_as_the_qa_wait(tmp_path: Path) -> None:
    """Only the pipeline's own awaiting-QA exit selects the wait reading."""
    capture = _capture(tmp_path, awaiting_qa_report_lines(RUN_ID, [OBLIGATION]))

    assert designed_wait(kind="deploy", exit_code=1, raw_capture=capture) is None


def test_a_successful_deploy_still_reports_completion(tmp_path: Path) -> None:
    capture = _capture(tmp_path, awaiting_qa_report_lines(RUN_ID, [OBLIGATION]))

    outcome = format_terminal_outcome(kind="deploy", exit_code=0, raw_capture=capture)

    assert "completed successfully" in outcome
