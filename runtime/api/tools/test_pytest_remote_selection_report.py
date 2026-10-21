"""A recorded CI wait tells the watching turn it may end."""

from __future__ import annotations

import json
import subprocess

from yoke_core.tools import pytest_remote_selection as routing
from yoke_core.tools import pytest_remote_selection_report as report

_RECORD = "yoke_core.domain.session_ci_wait_record.record_ci_run_wait"
_SESSION = "yoke_core.domain.session_ci_wait_record.ambient_session_id"


def _record(monkeypatch, *, session: str, warning: str = "") -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(_SESSION, lambda: session)
    monkeypatch.setattr(_RECORD, lambda **kw: calls.append(kw) or warning)
    report.record_wait(
        repo="acme/w",
        run_id="42",
        head_sha="a" * 40,
        continue_command="yoke watch pytest --impacted main --bounded",
    )
    return calls


def test_recorded_wait_says_end_the_turn(monkeypatch, capsys) -> None:
    calls = _record(monkeypatch, session="sess-1")

    assert calls[0]["run_id"] == "42"
    out = capsys.readouterr().out
    assert "ci wait recorded for run 42" in out
    assert "end the turn and do not poll GitHub" in out
    assert "`yoke watch pytest --impacted main --bounded`" in out


def test_refused_record_warns_and_promises_no_wake(monkeypatch, capsys) -> None:
    _record(monkeypatch, session="sess-1", warning="ci wait not recorded: down")

    out = capsys.readouterr().out
    assert "ci wait not recorded: down" in out
    assert "will not wake a stopped turn" in out
    assert "ci wait recorded" not in out


def test_no_session_records_and_prints_nothing(monkeypatch, capsys) -> None:
    calls = _record(monkeypatch, session="")

    assert calls == []
    assert capsys.readouterr().out == ""


_PLAN_LOG = (
    "=== failed job 1/1 · plan · job 7 · failure ===\n"
    "Error: ci_selection_plan: selection_exceeds_full_ci_share: the selection "
    "profiles at 3000s, 64% of the suite's 4700s (threshold 50%); no selection "
    "shard runs. Full CI answers this change: run the item's full QA case.\n"
)


def _adapter(monkeypatch, tmp_path, output: str) -> None:
    """The failed-log adapter saving its long report and naming the file."""
    saved = tmp_path / "reply.json"
    saved.write_text(json.dumps({"response": {"result": {"output": output}}}))
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=list(args),
            returncode=0,
            stdout=json.dumps({"success": True, "saved_response": str(saved)}),
            stderr="",
        ),
    )


def test_a_saved_failed_log_report_is_relayed_not_its_pointer(
    monkeypatch, capsys, tmp_path
) -> None:
    _adapter(monkeypatch, tmp_path, "FAILED tests/test_a.py::test_x - boom")

    text = report.relay_failed_log(project="yoke", repo="acme/w", run_id="42")

    assert text == "FAILED tests/test_a.py::test_x - boom"
    out = capsys.readouterr().out
    assert "FAILED tests/test_a.py::test_x" in out
    assert "saved_response" not in out


def test_a_plan_job_refusal_is_a_named_refusal_not_a_test_failure(
    monkeypatch, capsys, tmp_path
) -> None:
    _adapter(monkeypatch, tmp_path, _PLAN_LOG)
    monkeypatch.setattr(report, "record_wait", lambda **k: None)
    monkeypatch.setattr(report, "await_conclusion", lambda **k: "failure")
    monkeypatch.setattr(
        "yoke_core.domain.session_ci_wait_record.resolve_received_wait",
        lambda **k: "",
    )

    code = report.follow(
        project="yoke", repo="acme/w", run_id="42", source="dispatched",
        head_sha="a" * 40, description="", artifact_pattern="pytest-output-*",
        continue_command="", timeout_seconds=5,
    )

    assert code == routing.EXIT_REFUSED
    out = capsys.readouterr().out
    assert "concluded refused_by_plan exit=2" in out
    assert "selection_exceeds_full_ci_share: the selection profiles at 3000s" in out
    assert "run the item's full QA case" in out


def test_a_failed_test_log_stays_a_failure() -> None:
    assert report.plan_refusal("FAILED tests/test_a.py::test_x - boom") == ""
