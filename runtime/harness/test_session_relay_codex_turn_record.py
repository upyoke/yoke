"""Reading a Codex turn record back, and reporting only what it proves."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_contracts.session_control.function_ids import RELAY_TURN_END_FUNCTION_ID
from yoke_harness.session_relay_codex_turn_record import error_terminal_turn
from yoke_harness.session_relay_native_turn_end import (
    observed_turn_ends,
    report_native_turn_ends,
)


SESSION_ID = "01a057ed-a463-7ff1-82ac-bb688906dcd9"
TURN_ID = "01a057ed-a724-7b03-bdbe-4f3a313aec8d"
OBSERVED_AT = "2026-08-31T13:09:08.050Z"
INVENTORY = SimpleNamespace(
    relay_id="machine:m1",
    machine_id="22222222-2222-4222-8222-222222222222",
    project_ids=(1,),
)


def _tool_call() -> dict:
    return {
        "timestamp": "2026-08-31T13:09:02.472Z",
        "type": "response_item",
        "payload": {"type": "custom_tool_call", "call_id": "call_1", "name": "exec"},
    }


def _task_complete(error: dict | None) -> dict:
    return {
        "timestamp": OBSERVED_AT,
        "type": "event_msg",
        "payload": {
            "type": "task_complete",
            "turn_id": TURN_ID,
            "last_agent_message": None,
            "error": error,
        },
    }


def _rollout(root: Path, *events: dict, session_id: str = SESSION_ID) -> Path:
    day = root / "2026" / "08" / "31"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-31T09-06-27-{session_id}.jsonl"
    path.write_text("".join(f"{json.dumps(event)}\n" for event in events))
    return path


def _read(root: Path, session_id: str = SESSION_ID):
    return error_terminal_turn(session_id, transcript_roots=[root])


def test_a_turn_that_ended_on_a_vendor_error_is_reported(tmp_path):
    _rollout(
        tmp_path,
        _tool_call(),
        _task_complete(
            {
                "message": "Selected model is at capacity.",
                "codex_error_info": "server_overloaded",
            }
        ),
    )

    observed = _read(tmp_path)

    assert observed is not None
    assert observed.session_id == SESSION_ID
    assert observed.observed_at == OBSERVED_AT
    assert observed.evidence["codex_error_info"] == "server_overloaded"
    assert observed.evidence["turn_id"] == TURN_ID


def test_a_turn_that_ended_cleanly_is_not_reported(tmp_path):
    _rollout(tmp_path, _tool_call(), _task_complete(None))
    assert _read(tmp_path) is None


def test_a_turn_still_in_flight_is_not_reported(tmp_path):
    _rollout(tmp_path, _task_complete(None), _tool_call())
    assert _read(tmp_path) is None


def test_a_session_with_no_rollout_is_not_reported(tmp_path):
    _rollout(tmp_path, _task_complete({"message": "x"}), session_id="other")
    assert _read(tmp_path) is None


def test_an_unreadable_tail_is_not_reported(tmp_path):
    path = _rollout(tmp_path, _tool_call())
    path.write_text('{"timestamp": "2026-08-31T13:09:08.050Z", "payload": {')
    assert _read(tmp_path) is None


def test_a_surface_with_no_turn_record_reader_is_left_unread():
    assert (
        observed_turn_ends(
            [{"session_id": SESSION_ID, "executor_surface": "claude-cli"}]
        )
        == ()
    )


class _Recorder:
    def __init__(self, success: bool = True, reclassified=(SESSION_ID,)) -> None:
        self.calls: list[dict] = []
        self._response = SimpleNamespace(
            success=success,
            result={"reclassified": list(reclassified), "skipped": []},
            error=SimpleNamespace(code="unknown_function", message="skew"),
        )

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _report(dispatcher, probes, monkeypatch, observed):
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_end.TURN_RECORD_READERS",
        {"codex-cli": lambda session_id: observed},
    )
    return report_native_turn_ends(dispatcher, INVENTORY, probes)


def test_nothing_is_reported_when_the_control_plane_named_no_targets(monkeypatch):
    dispatcher = _Recorder()
    assert _report(dispatcher, None, monkeypatch, None) == ()
    assert dispatcher.calls == []


def test_nothing_is_reported_when_every_named_turn_is_still_running(monkeypatch):
    dispatcher = _Recorder()
    probes = [{"session_id": SESSION_ID, "executor_surface": "codex-cli"}]

    assert _report(dispatcher, probes, monkeypatch, None) == ()
    assert dispatcher.calls == []


def test_an_ended_turn_is_reported_with_its_record_evidence(monkeypatch, tmp_path):
    _rollout(
        tmp_path,
        _task_complete({"message": "at capacity", "codex_error_info": "overloaded"}),
    )
    observed = _read(tmp_path)
    dispatcher = _Recorder()
    probes = [{"session_id": SESSION_ID, "executor_surface": "codex-cli"}]

    assert _report(dispatcher, probes, monkeypatch, observed) == (SESSION_ID,)

    call = dispatcher.calls[0]
    assert call["function_id"] == RELAY_TURN_END_FUNCTION_ID
    reported = call["payload"]["turn_ends"][0]
    assert reported["session_id"] == SESSION_ID
    assert reported["observed_at"] == OBSERVED_AT
    assert reported["evidence"]["record"] == "codex_rollout_tail"


def test_a_server_that_refuses_the_report_leaves_the_poll_working(
    monkeypatch, tmp_path
):
    _rollout(tmp_path, _task_complete({"message": "at capacity"}))
    observed = _read(tmp_path)
    dispatcher = _Recorder(success=False)
    probes = [{"session_id": SESSION_ID, "executor_surface": "codex-cli"}]

    assert _report(dispatcher, probes, monkeypatch, observed) == ()
    assert dispatcher.calls
