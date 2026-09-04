"""Machine-local proof that a session's native process is gone."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_relay_process_liveness import (
    LAUNCH_HANDLE_SOURCE,
    PROCESS_ANCHOR_SOURCE,
    report_verified_dead_sessions,
    session_process_records,
    verified_dead_sessions,
)
from yoke_harness.session_relay_termination import NATIVE_HANDLE_DIRECTORY_NAME


LIVE_SESSION = "11111111-1111-4111-8111-111111111111"
DEAD_SESSION = "22222222-2222-4222-8222-222222222222"
LIVE_START = "Mon Aug 24 09:00:00 2026"
RECORDED_START = "Mon Aug 24 08:00:00 2026"


class _Inventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _Response:
    def __init__(self, success: bool, result=None, error=None) -> None:
        self.success = success
        self.result = result
        self.error = error


class _Dispatcher:
    def __init__(self, response: _Response) -> None:
        self.calls: list[dict] = []
        self._response = response

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return self._response


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _handle(state_dir: Path, session_id: str, pid: int, launch: str) -> None:
    _write(
        state_dir / NATIVE_HANDLE_DIRECTORY_NAME / f"{launch}.json",
        {
            "launch_id": launch,
            "target_session_id": session_id,
            "pid": pid,
            "process_start_time": RECORDED_START,
        },
    )


def _anchor(anchors: Path, session_id: str, pid: int, **extra) -> None:
    _write(
        anchors / f"{pid}.json",
        {
            "session_id": session_id,
            "anchor_pid": pid,
            "anchor_start_time": RECORDED_START,
            **extra,
        },
    )


def _start_time_of(live_pids: set[int]):
    def resolve(pid: int) -> str | None:
        return RECORDED_START if pid in live_pids else None

    return resolve


def test_records_read_both_families_and_compare_start_times(tmp_path: Path) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, LIVE_SESSION, 4001, "launch-live")
    _anchor(anchors, DEAD_SESSION, 4002)
    records = session_process_records(
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of({4001}),
    )
    by_session = {record.session_id: record for record in records}
    assert by_session[LIVE_SESSION].running is True
    assert by_session[LIVE_SESSION].source == LAUNCH_HANDLE_SOURCE
    assert by_session[DEAD_SESSION].running is False
    assert by_session[DEAD_SESSION].source == PROCESS_ANCHOR_SOURCE


def test_only_sessions_with_every_record_gone_are_verified_dead(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, LIVE_SESSION, 4001, "launch-live")
    _anchor(anchors, LIVE_SESSION, 4003)
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of({4001}),
    )
    assert [entry.session_id for entry in dead] == [DEAD_SESSION]
    assert dead[0].evidence == {
        "records_considered": 1,
        "sources": [LAUNCH_HANDLE_SOURCE],
        "pids": [4002],
        # The start time travels with the pid: it is what made the claim
        # checkable here, so the control plane's evidence can name the
        # process this record was written for rather than only its number.
        "process_start_times": {"4002": RECORDED_START},
        # A launch handle names the launch too, which is what lets the control
        # plane correct a launch still reading succeeded for a dead worker,
        # and is the evidence that ends a settled session without a TTL wait.
        "launch_id": "launch-dead",
    }


def test_a_session_without_any_record_is_never_reported(tmp_path: Path) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    anchors.mkdir(parents=True, exist_ok=True)
    assert (
        verified_dead_sessions(
            state_dir=tmp_path,
            anchors_dir=anchors,
            start_time_of=_start_time_of(set()),
        )
        == ()
    )


def test_a_shared_anchor_cannot_testify_about_one_session(tmp_path: Path) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _anchor(anchors, DEAD_SESSION, 4002, shared_by_multiple_sessions=True)
    assert (
        verified_dead_sessions(
            state_dir=tmp_path,
            anchors_dir=anchors,
            start_time_of=_start_time_of(set()),
        )
        == ()
    )


def test_report_dispatches_the_dead_sessions_and_returns_what_ended(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    dispatcher = _Dispatcher(_Response(True, {"ended": [DEAD_SESSION], "skipped": []}))
    ended = report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of(set()),
    )
    assert ended == (DEAD_SESSION,)
    call = dispatcher.calls[0]
    assert call["function_id"] == "session_control.relay.liveness"
    assert call["machine_id"] == "machine-1"
    assert call["sessions"][0]["session_id"] == DEAD_SESSION


def test_nothing_dead_means_no_dispatch_at_all(tmp_path: Path) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, LIVE_SESSION, 4001, "launch-live")
    dispatcher = _Dispatcher(_Response(True, {"ended": [], "skipped": []}))
    assert (
        report_verified_dead_sessions(
            dispatcher,
            _Inventory(),
            state_dir=tmp_path,
            anchors_dir=anchors,
            start_time_of=_start_time_of({4001}),
        )
        == ()
    )
    assert dispatcher.calls == []


def test_a_landed_report_prunes_the_spent_records(tmp_path: Path) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    _anchor(anchors, LIVE_SESSION, 4001)
    dispatcher = _Dispatcher(_Response(True, {"ended": [DEAD_SESSION], "skipped": []}))
    report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of({4001}),
    )
    handle = tmp_path / NATIVE_HANDLE_DIRECTORY_NAME / "launch-dead.json"
    assert not handle.exists()
    assert (anchors / "4001.json").exists(), "a live session keeps its record"


def test_a_spared_claim_holder_keeps_records_for_a_later_report(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    dispatcher = _Dispatcher(
        _Response(
            True,
            {
                "ended": [],
                "skipped": [{"session_id": DEAD_SESSION, "status": "claims_held"}],
            },
        )
    )
    report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of(set()),
    )
    assert (tmp_path / NATIVE_HANDLE_DIRECTORY_NAME / "launch-dead.json").exists()


def test_a_refused_report_keeps_the_records_for_the_next_poll(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    dispatcher = _Dispatcher(_Response(False, None, None))
    report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_start_time_of(set()),
    )
    assert (tmp_path / NATIVE_HANDLE_DIRECTORY_NAME / "launch-dead.json").exists()


def test_a_server_that_does_not_serve_the_function_is_survived(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")

    class _Error:
        code = "function_version_skew"
        message = "server predates this client build"

    dispatcher = _Dispatcher(_Response(False, None, _Error()))
    assert (
        report_verified_dead_sessions(
            dispatcher,
            _Inventory(),
            state_dir=tmp_path,
            anchors_dir=anchors,
            start_time_of=_start_time_of(set()),
        )
        == ()
    )
    assert dispatcher.calls[0]["function_id"] == "session_control.relay.liveness"


def test_a_reused_pid_reads_as_gone_rather_than_as_the_recorded_native(
    tmp_path: Path,
) -> None:
    """Another process holding the number is not the native that was recorded."""
    anchors = tmp_path / ANCHORS_DIR_NAME
    anchors.mkdir(parents=True, exist_ok=True)
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")

    def _reused(pid: int) -> str:
        del pid
        return LIVE_START

    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_reused,
    )

    assert [entry.session_id for entry in dead] == [DEAD_SESSION]
    assert dead[0].evidence["process_start_times"] == {"4002": RECORDED_START}
