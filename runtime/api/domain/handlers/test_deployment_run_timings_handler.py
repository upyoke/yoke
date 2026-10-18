"""Release phase timings persist from the driver and read back by run."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import deployment_start_timing as timing
from yoke_core.domain.handlers.deployment_run_timings import (
    handle_deployment_run_timings,
    handle_deployment_run_timings_record,
)

RUN = "run-timings-001"


def _request(function: str, payload: dict | None = None, run: str = RUN):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind="workflow_run", workflow_run_id=run),
        payload=payload or {},
    )


def _record(step, phase, second, **extra):
    record = {
        "run_id": RUN,
        "step": step,
        "phase": phase,
        "timestamp": f"2026-10-18T00:00:0{second}.000000Z",
        "transport": "https",
        **extra,
    }
    return record


def _store(batch_id, records):
    return handle_deployment_run_timings_record(
        _request(
            "deployment_runs.timings.record",
            {"batch_id": batch_id, "records": records},
        )
    )


def _read(run: str = RUN):
    return handle_deployment_run_timings(_request("deployment_runs.timings", run=run))


def test_recorded_timings_read_back_in_order_with_step_totals(test_db) -> None:
    insert_deployment_run(test_db, id=RUN, status="succeeded")
    test_db.commit()
    first = [
        _record("pin_read", "start", 1),
        _record("pin_read", "end", 2, elapsed_ms=40.5, outcome="ok"),
    ]
    later = [
        _record("qa_seed", "start", 3),
        _record("qa_seed", "end", 4, elapsed_ms=10, outcome="failed"),
        _record("qa_seed", "end", 5, elapsed_ms=12.25, outcome="ok"),
    ]
    assert _store("batch-b", later).result_payload["recorded"] == 3
    stored = _store("batch-a", first)
    assert stored.primary_success, stored.error

    replay = _store("batch-a", first).result_payload
    assert (replay["recorded"], replay["already_recorded"]) == (0, 2)

    result = _read().result_payload
    assert result["status"] == "succeeded"
    assert result["note"] is None
    assert [(r["step"], r["phase"]) for r in result["records"]] == [
        ("pin_read", "start"),
        ("pin_read", "end"),
        ("qa_seed", "start"),
        ("qa_seed", "end"),
        ("qa_seed", "end"),
    ]
    assert result["records"][1]["transport"] == "https"
    assert result["steps"] == [
        {"step": "pin_read", "elapsed_ms": 40.5, "count": 1, "outcomes": ["ok"]},
        {
            "step": "qa_seed",
            "elapsed_ms": 22.25,
            "count": 2,
            "outcomes": ["failed", "ok"],
        },
    ]


def test_invalid_records_and_unknown_runs_refuse_by_name(test_db) -> None:
    insert_deployment_run(test_db, id=RUN, status="executing")
    test_db.commit()
    other_run = _store("batch-x", [{**_record("pin_read", "start", 1), "run_id": "x"}])
    assert other_run.error.code == "payload_invalid"
    assert "must equal the target run" in other_run.error.message
    pulse = _store("batch-y", [_record("pin_read", "running", 1)])
    assert "phase must be 'start' or 'end'" in pulse.error.message
    bad_clock = _store(
        "batch-z", [{**_record("pin_read", "start", 1), "timestamp": ""}]
    )
    assert "timestamp must be a UTC instant" in bad_clock.error.message

    empty = _read().result_payload
    assert empty["records"] == [] and "no timings recorded" in empty["note"]
    assert _read("run-absent").error.code == "not_found"


def test_closed_scope_sends_only_its_runs_start_and_end_records(monkeypatch) -> None:
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, error=None, result={})

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", dispatch
    )
    with timing.timing_scope("run-persist", persist=True):
        with timing.start_step("pin_read"):
            pass
        timing.emit_records(
            [
                {"run_id": "run-persist", "step": "context", "phase": "end"},
                {"run_id": "run-persist", "step": "context", "phase": "running"},
            ]
        )
    with timing.timing_scope("run-silent"):
        with timing.start_step("pin_read"):
            pass

    assert len(calls) == 1
    assert calls[0]["function_id"] == "deployment_runs.timings.record"
    assert calls[0]["target"].workflow_run_id == "run-persist"
    sent = calls[0]["payload"]["records"]
    assert [(r["step"], r["phase"]) for r in sent] == [
        ("pin_read", "start"),
        ("pin_read", "end"),
        ("context", "end"),
    ]


def test_refused_timing_write_is_reported_without_failing_the_run(
    monkeypatch, capsys
) -> None:
    error = SimpleNamespace(
        code="function_not_served", message="below floor", recovery_hint=""
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_: SimpleNamespace(success=False, error=error, result=None),
    )
    with timing.timing_scope("run-refused", persist=True):
        with timing.start_step("pin_read"):
            pass

    err = capsys.readouterr().err
    assert timing.REFUSAL_PREFIX + "run run-refused: function_not_served" in err
    assert "yoke deployment-runs timings run-refused" in err
