"""Native Claude job clocks and exact idle eligibility without host actions."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_harness.claude_runtime_records import claude_job_state
from yoke_harness import session_relay_claude_idle_hosts as idle_hosts
from runtime.harness.test_session_relay_claude_idle_hosts import (
    NOW,
    _Dispatcher,
    _Inventory,
    _Response,
    _fixture,
)


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-03T20:08:00.176001Z",
        "2026-09-04T05:08:00.176001+09:00",
        "2026-09-03T16:08:00.176001-04:00",
    ],
)
def test_foreign_job_clock_retains_native_microseconds_and_file_bytes(tmp_path, value):
    path = tmp_path / "jobs" / "job1" / "state.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps(
        {
            "state": "done",
            "tempo": "idle",
            "updatedAt": value,
            "evidence": "opaque clock 2026-09-03",
        }
    ).encode()
    path.write_bytes(raw)
    assert claude_job_state("job1", tmp_path) == {
        "state": "done",
        "tempo": "idle",
        "updated_at": parse_instant("2026-09-03T20:08:00.176001Z"),
    }
    assert path.read_bytes() == raw


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-09-03",
        "2026-09-03T20:08:00",
        "2026-02-30T20:08:00Z",
        1788466080,
        False,
    ],
)
def test_malformed_foreign_job_clock_refuses_read_without_rewriting(tmp_path, value):
    path = tmp_path / "jobs" / "job1" / "state.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps({"state": "done", "updatedAt": value}).encode()
    path.write_bytes(raw)
    assert claude_job_state("job1", tmp_path) is None
    assert path.read_bytes() == raw


def test_missing_foreign_job_clock_remains_unknown(tmp_path):
    path = tmp_path / "jobs" / "job1" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"state":"done"}')
    assert claude_job_state("job1", tmp_path)["updated_at"] is None


@pytest.mark.parametrize("delta,eligible", [(-1, False), (0, True), (1, True)])
@pytest.mark.parametrize(
    "zone", [timezone.utc, timezone(timedelta(hours=9)), timezone(timedelta(hours=-4))]
)
def test_idle_cutoff_compares_native_microseconds_before_reporting(
    delta, eligible, zone
):
    processes, records, _jobs = _fixture()
    updated = NOW - timedelta(
        seconds=idle_hosts.IDLE_HOST_THRESHOLD_SECONDS, microseconds=delta
    )
    hosts = idle_hosts.plan_idle_hosts(
        processes,
        now=NOW.astimezone(zone),
        session_record_of=records,
        job_state_of=lambda _job: {
            "state": "done",
            "tempo": "idle",
            "updated_at": updated.astimezone(zone),
        },
    )
    assert [host.pid for host in hosts] == (
        [101, 105, 107, 109, 111] if eligible else []
    )
    assert all(
        host.idle_seconds == idle_hosts.IDLE_HOST_THRESHOLD_SECONDS for host in hosts
    )


@pytest.mark.parametrize(
    "value",
    [None, "", "2026-09-03", "2026-09-03T20:08:00", datetime(2026, 9, 3), 1788466080],
)
def test_unknown_or_invalid_job_clock_never_qualifies_a_host(value):
    processes, records, _jobs = _fixture()
    assert (
        idle_hosts.plan_idle_hosts(
            processes,
            now=NOW,
            session_record_of=records,
            job_state_of=lambda _job: {"state": "stopped", "updated_at": value},
        )
        == ()
    )


@pytest.mark.parametrize("value", ["", "2026-09-03", datetime(2026, 9, 3), 1788466080])
def test_invalid_current_clock_refuses_before_process_inventory(monkeypatch, value):
    def inventory():
        pytest.fail("invalid clocks must refuse before any process read")

    monkeypatch.setattr(idle_hosts, "process_inventory", inventory)
    with pytest.raises(InvalidInstant):
        idle_hosts.reclaim_idle_claude_hosts(_Dispatcher(), _Inventory(), now=value)


def test_default_current_clock_is_native_and_live_sessions_remain_untouched(
    monkeypatch,
):
    processes, records, jobs = _fixture()
    monkeypatch.setattr(idle_hosts, "utc_now", lambda: NOW)
    dispatcher = _Dispatcher(_Response(True, {"ended": []}))

    def forbidden(_host):
        pytest.fail("live sessions must remain untouched")

    # Only tracked, open jobs; this fixture never invokes a real process action.
    def jobs_without_exited(job):
        value = jobs(job)
        return {**value, "state": "done"} if value else None

    assert (
        idle_hosts.reclaim_idle_claude_hosts(
            dispatcher,
            _Inventory(),
            processes=processes,
            session_record_of=records,
            job_state_of=jobs_without_exited,
            signal_host=forbidden,
            stop_job=forbidden,
        )
        == ()
    )
    assert dispatcher.calls[0]["hosts"] == [
        {"session_id": records(pid)["session_id"], "pid": pid} for pid in (101, 109)
    ]
