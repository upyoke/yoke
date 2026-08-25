"""CI QA progress stays live on stderr while stdout remains machine-readable."""

from __future__ import annotations

import io

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    wire_ci_case,
)
from yoke_core.domain import (
    deploy_pipeline_reporting,
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


def test_entry_run_waits_are_live_before_polling(monkeypatch, capsys):
    pending = qa_case_ci_lane.WorkflowRun(
        "77",
        "in_progress",
        "",
        "https://github.test/actions/runs/77",
        LANE_HEAD,
    )
    runs = iter([None, None, pending, completed_run(LANE_HEAD)])
    monkeypatch.setattr(
        qa_case_ci_lane,
        "find_pull_request_run",
        lambda **kwargs: next(runs),
    )

    def _await(**kwargs):
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.count("no run id yet") == 2
        assert "requirement=41 covering run=77" in captured.err
        assert "https://github.test/actions/runs/77" in captured.err
        return 0, "success"

    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", _await)
    clock = {"now": 0.0}

    def _sleep(seconds: float) -> None:
        clock["now"] += seconds

    result = qa_case_ci_entry_run.await_entry_run(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        head_sha=LANE_HEAD,
        timeout_seconds=60,
        sleep=_sleep,
        monotonic=lambda: clock["now"],
    )

    assert result == completed_run(LANE_HEAD)
