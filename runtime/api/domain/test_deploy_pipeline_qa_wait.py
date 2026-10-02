"""The deployment driver waits in-process for scoped QA, but only boundedly."""

from __future__ import annotations

from yoke_core.domain.deploy_pipeline_qa_wait import (
    AWAITING_SCOPED_QA,
    dispatch_until_qa_resolves,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_returns_an_immediate_non_waiting_result_without_sleeping() -> None:
    clock = _Clock()

    result = dispatch_until_qa_resolves(
        lambda: (0, "passed"),
        timeout_seconds=30,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == (0, "passed")
    assert clock.sleeps == []


def test_repolls_until_scoped_qa_passes() -> None:
    clock = _Clock()
    outcomes = iter([(AWAITING_SCOPED_QA, "member pending")] * 2 + [(0, "accepted")])

    result = dispatch_until_qa_resolves(
        lambda: next(outcomes),
        timeout_seconds=30,
        poll_interval_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == (0, "accepted")
    assert clock.sleeps == [15, 15]


def test_timeout_returns_the_wait_code_with_recovery() -> None:
    clock = _Clock()
    calls = 0

    def pending() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        return AWAITING_SCOPED_QA, "member 42 has no passing run"

    result = dispatch_until_qa_resolves(
        pending,
        timeout_seconds=31,
        poll_interval_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert "timed out after 31s" in result[1]
    assert "re-drive this deployment run from the QA stage" in result[1]
    assert clock.sleeps == [15, 15, 1]
    assert calls == 4


def test_zero_timeout_performs_one_probe() -> None:
    clock = _Clock()
    calls = 0

    def pending() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        return AWAITING_SCOPED_QA, "pending"

    result = dispatch_until_qa_resolves(
        pending,
        timeout_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert calls == 1
    assert clock.sleeps == []


def test_pipeline_scoped_qa_park_is_a_designed_watcher_wait(
    monkeypatch, capsys, tmp_path
):
    from yoke_core.domain import deploy_pipeline as pipeline
    from yoke_core.domain.deployment_run_completion_preconditions import (
        held_stage_report_lines,
    )
    from yoke_core.tools._watch_designed_waits import designed_wait

    run_id = "run-scoped-qa"
    context = {
        "run": {
            "id": run_id,
            "project": "example",
            "flow": "qa-flow",
            "status": "executing",
        },
        "members": [{"item_id": 42}],
        "stages": [{"name": "member-qa", "step_runner": "deployment-qa"}],
    }
    monkeypatch.setattr(pipeline.control_plane, "execution_context", lambda _r: context)
    monkeypatch.setattr(pipeline.control_plane, "project_field", lambda *a: "")
    monkeypatch.setattr(pipeline.control_plane, "seed_qa", lambda _r: None)
    monkeypatch.setattr(
        pipeline.control_plane,
        "held_qa_report_lines",
        lambda r, s: held_stage_report_lines(
            r, s, ["requirement 1 pending", "requirement 2 pending"]
        ),
    )
    monkeypatch.setattr(pipeline, "resolve_project_checkout_path", lambda _p: "/repo")
    monkeypatch.setattr(pipeline, "resolve_flow_gate_branch", lambda *a: "main")
    monkeypatch.setattr(
        pipeline, "_resolve_and_verify_branch", lambda *a, **k: (True, "42", "main")
    )
    monkeypatch.setattr(
        pipeline.stage_checks, "check_completion_stage_qa", lambda *a, **k: None
    )
    monkeypatch.setattr(pipeline, "_set_deploy_stage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_emit_run_event", lambda *a, **k: None)
    monkeypatch.setattr(
        pipeline,
        "dispatch_until_qa_resolves",
        lambda *a, **k: (AWAITING_SCOPED_QA, "timed out awaiting scoped QA"),
    )

    rc = pipeline.run_pipeline(run_id, sd="/tmp/sd")

    assert rc == pipeline.EXIT_AWAITING_QA
    report = capsys.readouterr().err
    assert "2 blocking QA obligation(s)" in report
    assert "timed out awaiting scoped QA" in report
    capture = tmp_path / "deploy.log"
    capture.write_text(report)
    wait = designed_wait(kind="deploy", exit_code=rc, raw_capture=capture)
    assert wait is not None
    assert f"for run {run_id}" in wait.cause
    assert run_id in wait.continuation
