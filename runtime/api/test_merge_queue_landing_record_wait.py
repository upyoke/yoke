"""The waiting process consumes only fresh control-plane landing records."""

import ast
from pathlib import Path

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    dispatch_for,
    land,
    landing_record,
    ok_response,
    wire_happy_path,
)
from yoke_core.domain import merge_queue_landing_wait as wait_mod
from yoke_core.domain.merge_queue_landing_record_state import PENDING
from yoke_core.domain.merge_queue_readiness import (
    ENQUEUED,
    MERGE_WHEN_READY_CONSUMED,
)


def test_observe_call_uses_the_merge_registry_skew_degradation(monkeypatch):
    sent = object()
    announced: list[str] = []
    observed = landing_record()

    def degraded(**kwargs):
        assert kwargs["function_id"] == wait_mod.OBSERVE_FUNCTION_ID
        assert kwargs["dispatch"] is sent
        kwargs["announce"]("[degraded] same-universe observation")
        return ok_response({"record": observed})

    monkeypatch.setattr(
        wait_mod.control_plane_function_degradation,
        "dispatch_through_paired_admin_on_skew",
        degraded,
    )

    record, result, error = wait_mod._read_server_record(
        sent,
        item_id=1,
        announce=announced.append,
    )

    assert error == ""
    assert result["record"] == observed
    assert record is not None and record.state == observed["state"]
    assert record.queue_holding == ENQUEUED
    assert record.queue_entry_state == "AWAITING_CHECKS"
    assert record.merge_when_ready == MERGE_WHEN_READY_CONSUMED
    assert announced == ["[degraded] same-universe observation"]


def test_a_concurrent_first_refresh_can_finish_before_a_record_exists(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])

    outcome = land(landing_records=[None, landing_record()])

    assert outcome.ok


def test_a_stale_record_names_its_refresh_time_and_recovery(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    observed_at = "2026-09-04T01:00:00Z"

    outcome = land(
        landing_stale=True,
        landing_records=[
            landing_record(
                PENDING,
                narrative="pull request 42: queue-entry=enqueued",
                observed_at=observed_at,
            )
        ],
    )

    assert not outcome.ok
    assert outcome.exit_code == 9
    assert "landing_record_stale" in outcome.error
    assert observed_at in outcome.error
    assert "control plane can reach GitHub" in outcome.error
    assert "must not substitute local gh/git polling" in outcome.error


def test_default_wait_invokes_the_server_observer_once_per_minute():
    elapsed = [0.0]
    delays: list[float] = []
    calls: list[str] = []
    base_dispatch = dispatch_for(
        {"YOK-200": {}},
        landing_records=[
            landing_record(PENDING),
            landing_record(PENDING),
            landing_record(PENDING),
            landing_record(),
        ],
    )

    def dispatch(**kwargs):
        calls.append(str(kwargs["function_id"]))
        return base_dispatch(**kwargs)

    def sleep(seconds: float):
        delays.append(seconds)
        elapsed[0] += seconds

    refusal = wait_mod.wait_for_queue_landing(
        pr_num="42",
        target="main",
        item_id=1,
        public_ref="YOK-200",
        resume_command="yoke merge item YOK-200 --wait",
        dispatch=dispatch,
        sleep=sleep,
        monotonic=lambda: elapsed[0],
        deadline_seconds=240.0,
        emit=lambda _line: None,
    )

    assert refusal is None
    assert delays == [60.0, 60.0, 60.0]
    assert calls == [wait_mod.OBSERVE_FUNCTION_ID] * 4


def test_wait_module_has_no_local_github_or_process_reader_dependency():
    tree = ast.parse(Path(wait_mod.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert "subprocess" not in imported
    assert not any(name.startswith("yoke_core.engines") for name in imported)
    assert "yoke_core.domain.merge_queue_landing_verdict" not in imported


def test_partial_server_record_is_a_named_refresh_failure(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    partial = landing_record()
    partial.pop("queue_entry_state")

    outcome = land(landing_records=[partial])

    assert not outcome.ok
    assert outcome.exit_code == 9
    assert "landing_record_refresh_failed" in outcome.error
    assert "landing record response was invalid" in outcome.error
    assert "queue_entry_state" in outcome.error
