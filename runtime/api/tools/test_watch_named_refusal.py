"""A named ``Blocked (code):`` refusal is the deploy watch's terminal cause."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from yoke_core.domain import deploy_pipeline_gates
from yoke_core.domain import watch_capture_binding as _watch_capture_binding
from yoke_core.domain import watch_runner as _watch_runner
from yoke_core.domain.deploy_pipeline import EXIT_AWAITING_QA
from yoke_core.domain.deployment_run_completion_preconditions import (
    awaiting_qa_report_lines,
)
from yoke_core.domain.watch_terminal_outcome import format_terminal_outcome
from yoke_core.tools import watch_deploy

MISSING_SHA = "a" * 40


def _release_source_refusal(tmp_path: Path) -> str:
    ok, message = deploy_pipeline_gates._verify_branch_merged(
        "member", "YOK-1", str(tmp_path), MISSING_SHA, public_ref="YOK-1"
    )
    assert not ok
    return message


def test_deploy_watch_shows_the_named_release_refusal(tmp_path: Path) -> None:
    refusal = _release_source_refusal(tmp_path)
    child = tmp_path / "observer.py"
    child.write_text(
        "import sys\n"
        "print('Stage observer starting for run run-20261127-019')\n"
        f"print({refusal!r}, file=sys.stderr)\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    raw = tmp_path / "deploy.raw"
    progress = tmp_path / "deploy.progress"
    _watch_capture_binding.stamp_writer(progress, "deploy")
    direct = io.StringIO()

    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(child)],
        classifier=watch_deploy.classify_deploy_line,
        raw_capture=raw,
        progress_capture=progress,
        kind="deploy",
        stdout_stream=direct,
        outcome_only=True,
    )

    out = direct.getvalue()
    assert rc == 3
    assert "terminal cause not diagnosed" not in out
    assert "# watch_deploy failure: Blocked (release_source_unavailable):" in out
    assert f"frozen source '{MISSING_SHA}' is not a readable full commit" in out
    assert "Restore the run's source commit in the project checkout" in out
    assert "exit=3;" in out
    assert "# watch_deploy exit=3" in out


def _capture(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "raw.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_named_refusal_outranks_a_trailing_stage_summary(tmp_path: Path) -> None:
    refusal = _release_source_refusal(tmp_path)
    capture = _capture(tmp_path, [refusal, "Error: stage observer start failed"])

    outcome, watch_exit = format_terminal_outcome(
        kind="deploy", exit_code=3, raw_capture=capture
    )

    assert watch_exit == 3
    assert "failure: Blocked (release_source_unavailable):" in outcome


def test_an_explicit_terminal_error_still_wins(tmp_path: Path) -> None:
    capture = _capture(
        tmp_path,
        [
            _release_source_refusal(tmp_path),
            "Terminal error: driver lost; retry with yoke watch deploy",
        ],
    )

    outcome, _ = format_terminal_outcome(kind="deploy", exit_code=3, raw_capture=capture)

    assert "failure: Terminal error: driver lost" in outcome
    assert "recovery: retry with yoke watch deploy" in outcome


def test_designed_qa_wait_is_not_read_as_a_refusal(tmp_path: Path) -> None:
    capture = _capture(
        tmp_path,
        [
            "Blocked (example_gate): earlier gate notice",
            *awaiting_qa_report_lines("run-20261127-019", ["item-qa YOK-1 pending"]),
        ],
    )

    outcome, watch_exit = format_terminal_outcome(
        kind="deploy", exit_code=EXIT_AWAITING_QA, raw_capture=capture
    )

    assert watch_exit == 0
    assert "outcome: waiting" in outcome
    assert "Blocked" not in outcome


def test_unanchored_blocked_prose_is_not_a_cause(tmp_path: Path) -> None:
    capture = _capture(tmp_path, ["Item YOK-1 Blocked (by operator): paused"])

    outcome, _ = format_terminal_outcome(kind="deploy", exit_code=3, raw_capture=capture)

    assert "terminal cause not diagnosed" in outcome
