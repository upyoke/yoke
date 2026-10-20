"""The deployment driver waits in-process for scoped QA, but only boundedly."""

from __future__ import annotations

import threading
import time

import pytest

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
        fingerprint=lambda: str(clock.now),
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
        fingerprint=lambda: str(clock.now),
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
        fingerprint=lambda: str(clock.now),
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
        fingerprint=lambda: str(clock.now),
        timeout_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert calls == 1
    assert clock.sleeps == []


def test_a_dispatch_blocked_past_the_deadline_ends_the_wait_named() -> None:
    release = threading.Event()
    calls = 0

    def dispatch() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        if calls > 1:
            release.wait()
        return AWAITING_SCOPED_QA, "member 42 has no passing run"

    started = time.monotonic()
    try:
        result = dispatch_until_qa_resolves(
            dispatch,
            fingerprint=lambda: str(time.monotonic()),
            timeout_seconds=0.3,
            poll_interval_seconds=0.05,
            write=lambda _line: None,
        )
    finally:
        release.set()
    elapsed = time.monotonic() - started

    assert result[0] == AWAITING_SCOPED_QA
    assert elapsed < 0.3 + 0.5
    assert "member 42 has no passing run" in result[1]
    assert "timed out after 0.3s awaiting scoped QA" in result[1]
    assert "had no answer when the deadline passed" in result[1]
    assert "re-drive this deployment run from the QA stage" in result[1]


def test_a_dispatch_failure_inside_the_wait_reaches_the_driver() -> None:
    calls = 0

    def dispatch() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("deployment_outcome_unknown: lost on all sends")
        return AWAITING_SCOPED_QA, "pending"

    with pytest.raises(RuntimeError, match="deployment_outcome_unknown"):
        dispatch_until_qa_resolves(
            dispatch,
            fingerprint=lambda: str(time.monotonic()),
            timeout_seconds=30,
            poll_interval_seconds=0.01,
            write=lambda _line: None,
        )


def test_status_lines_appear_every_few_polls() -> None:
    clock = _Clock()
    lines: list[str] = []

    result = dispatch_until_qa_resolves(
        lambda: (AWAITING_SCOPED_QA, "member A: no run; member B: no run"),
        fingerprint=lambda: str(clock.now),
        timeout_seconds=120,
        poll_interval_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        write=lines.append,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert lines[0] == (
        "Waiting by design: scoped QA obligations on this deployment run to "
        "settle; checks every 15s; prints a status line every 60s; gives up "
        "after 2m."
    )
    assert lines[1:] == [
        "Still waiting for scoped QA: 60s elapsed of 2m; 2 blocker(s) outstanding.",
        "Still waiting for scoped QA: 2m elapsed of 2m; 2 blocker(s) outstanding.",
    ]


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
        "members": [{"public_ref": "ITEM-42"}],
        "stages": [{"name": "member-qa", "step_runner": "deployment-qa"}],
    }
    monkeypatch.setattr(pipeline.control_plane, "execution_context", lambda _r: context)
    monkeypatch.setattr(pipeline.control_plane, "project_field", lambda *a: "")
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
        pipeline,
        "_resolve_and_verify_branch",
        lambda *a, **k: (True, "ITEM-42", "main"),
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


def test_unchanged_fingerprint_dispatches_only_initially_and_at_deadline():
    clock = _Clock()
    calls = []
    result = dispatch_until_qa_resolves(
        lambda: calls.append(clock.now) or (AWAITING_SCOPED_QA, "still pending"),
        fingerprint=lambda: "same",
        timeout_seconds=31,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert calls == [0, 31]
    assert result[0] == AWAITING_SCOPED_QA


def test_changed_fingerprint_dispatches_and_resolves_before_deadline():
    clock = _Clock()
    calls = []

    def dispatch():
        calls.append(clock.now)
        return (0, "accepted") if clock.now else (AWAITING_SCOPED_QA, "pending")

    result = dispatch_until_qa_resolves(
        dispatch,
        fingerprint=lambda: "changed" if clock.now >= 30 else "same",
        timeout_seconds=60,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result == (0, "accepted")
    assert calls == [0, 30]
