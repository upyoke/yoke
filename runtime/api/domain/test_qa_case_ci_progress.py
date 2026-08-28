"""CI QA progress stays live on stderr while stdout remains machine-readable."""

from __future__ import annotations

import io

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    in_flight_run,
    wire_ci_case,
)
from yoke_core.domain import (
    deploy_pipeline_reporting,
    qa_case_ci_covering_run,
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_progress,
    qa_case_ci_run,
)


class _FlushRecorder(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_poll_relay_flushes_stdout_lines_to_the_selected_stream():
    stream = _FlushRecorder()

    with qa_case_ci_progress.relay_poll_output(stream):
        print("  Workflow status: waiting")

    assert stream.getvalue() == "  Workflow status: waiting\n"
    assert stream.flush_count >= 2


def test_qa_poll_output_uses_stderr(monkeypatch, capsys):
    def _poll(*args, **kwargs):
        print("  Workflow status: in_progress")
        return 0, "success"

    monkeypatch.setattr(
        deploy_pipeline_reporting,
        "_poll_github_actions",
        _poll,
    )

    assert qa_case_ci_lane.await_workflow(
        project="yoke",
        repo="acme/widgets",
        run_id="77",
        timeout_seconds=60,
    ) == (0, "success")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Workflow status: in_progress" in captured.err


def test_dispatched_run_is_announced_before_the_wait(
    monkeypatch,
    tmp_path,
    capsys,
):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)

    monkeypatch.setattr(
        qa_case_ci_lane,
        "dispatch_workflow",
        lambda **kwargs: "9182736",
    )

    def _await(**kwargs):
        captured = capsys.readouterr()
        assert captured.out == ""
        lines = captured.err.splitlines()
        dispatching = next(i for i, line in enumerate(lines) if "dispatching" in line)
        identified = next(i for i, line in enumerate(lines) if "run=9182736" in line)
        assert dispatching < identified
        assert "requirement=41" in lines[dispatching]
        assert "no run id yet" in lines[dispatching]
        assert (
            "https://github.com/acme/widgets/actions/runs/9182736" in lines[identified]
        )
        recovery = "\n".join(lines[identified + 1:])
        assert (
            "yoke github-actions failed-log acme/widgets 9182736 "
            "--project <project>"
        ) in recovery
        assert "gh run watch 9182736 --repo acme/widgets" in recovery
        assert (
            "gh api --method POST "
            "repos/acme/widgets/actions/runs/9182736/force-cancel"
        ) in recovery
        assert "yoke qa case run --requirement-id 41" in recovery
        return 0, "success"

    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", _await)

    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert result["verdict"] == "pass"
    assert result["ci_run_id"] == "9182736"


def test_entry_run_waits_are_live_while_the_run_has_no_id_yet(
    monkeypatch, capsys,
):
    """Appearance waits narrate; naming the run is the runner's job."""
    runs = iter([None, None, completed_run(LANE_HEAD)])
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **kwargs: next(runs),
    )
    clock = {"now": 0.0}

    result = qa_case_ci_entry_run.find_entry_run(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        head_sha=LANE_HEAD,
        timeout_seconds=60,
        sleep=lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
        monotonic=lambda: clock["now"],
    )

    captured = capsys.readouterr()
    assert result == completed_run(LANE_HEAD)
    assert captured.out == ""
    assert captured.err.count("no run id yet") == 2
    assert "run=77" not in captured.err


def test_an_attached_run_is_announced_as_attached_before_the_wait(
    monkeypatch, tmp_path, capsys,
):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **kwargs: in_flight_run(LANE_HEAD),
    )

    def _await(**kwargs):
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "requirement=41 attached run=77" in captured.err
        assert "dispatching" not in captured.err
        assert "https://github.test/actions/runs/77" in captured.err
        return 0, "success"

    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", _await)

    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert result["ci_run_source"] == "attached"
    assert result["verdict"] == "pass"


def test_the_run_announcement_teaches_the_interrupted_recovery(
    monkeypatch, tmp_path, capsys,
):
    """An interrupted gate is why adoption exists; the run line says so."""
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_lane, "dispatch_workflow", lambda **kwargs: "9182736",
    )
    monkeypatch.setattr(
        qa_case_ci_lane, "await_workflow", lambda **kwargs: (0, "success"),
    )

    qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    recovery = capsys.readouterr().err
    assert "if this invocation is interrupted".casefold() in recovery.casefold()
    assert "yoke qa case run --requirement-id 41" in recovery
    assert "re-executed" in recovery
