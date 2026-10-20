"""Start diagnostics survive failures and preflight-to-child capture handoff."""

import json
from unittest.mock import Mock
import pytest
from yoke_core.domain import deployment_start_timing as timing
from yoke_core.tools.deploy_start_preflight import prepare_driver, launch_watched_child


def test_steps_flush_identity_and_failure_elapsed(capsys, monkeypatch):
    monkeypatch.setattr(timing, "_transport", lambda: "https")
    clock = iter([10.0, 10.125])
    monkeypatch.setattr(timing, "monotonic", lambda: next(clock))
    with timing.timing_scope("run-timing"):
        timing.timing_facts(source_sha="a" * 40, member_count=3)
        with pytest.raises(ValueError), timing.start_step("qa_seed"):
            start = capsys.readouterr().out
            assert '"phase": "start"' in start
            raise ValueError("named refusal")
    end = capsys.readouterr().out
    record = json.loads(end.removeprefix(timing.PREFIX))
    assert record["outcome"] == "failed" and record["elapsed_ms"] == 125
    assert record["source_sha"] == "a" * 40
    assert record["member_count"] == 3 and record["transport"] == "https"


def test_preflight_writes_before_return_and_child_launch_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(timing, "_transport", lambda: "local-postgres")
    raw = tmp_path / "driver.log"

    def prepare(run_id):
        assert '"phase": "start"' in raw.read_text()
        return {"pin": run_id}

    assert prepare_driver("run-timing", raw, prepare) == {"pin": "run-timing"}
    launch = Mock(return_value="child")
    with raw.open("a") as stream:
        assert (
            launch_watched_child("deploy", stream, launch, ["python3", "run-timing"])
            == "child"
        )
    records = [
        json.loads(line.removeprefix(timing.PREFIX))
        for line in raw.read_text().splitlines()
    ]
    assert [(r["step"], r["phase"]) for r in records] == [
        ("driver_preflight", "start"),
        ("driver_preflight", "end"),
        ("child_start", "start"),
        ("child_start", "end"),
    ]


def test_reexec_child_records_launch_completion(capsys, monkeypatch):
    monkeypatch.setattr(timing, "_transport", lambda: "local-postgres")
    clock = iter([10.0, 10.2])
    monkeypatch.setattr(timing, "monotonic", lambda: next(clock))
    env = {}
    with timing.timing_scope("run-exec"):
        timing.begin_reexec(env)
    timing.finish_reexec("run-exec", environment=env)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    records = [json.loads(line.removeprefix(timing.PREFIX)) for line in lines]
    assert [r["phase"] for r in records] == ["start", "end"]
    assert records[1]["elapsed_ms"] == 200
    assert env == {}


def test_running_phase_keeps_identity_counts_and_failure(monkeypatch):
    from threading import Event

    reported = Event()
    release = Event()

    class PulseEvent:
        def wait(self, seconds):
            assert seconds == 30
            if not reported.is_set():
                return False
            return release.wait(1)

        def set(self):
            release.set()

    emit = timing._emit

    def record(*args, **kwargs):
        emit(*args, **kwargs)
        if args[1] == "running":
            reported.set()

    monkeypatch.setattr(timing, "Event", PulseEvent)
    monkeypatch.setattr(timing, "_emit", record)
    with timing.timing_scope("run-copy", collect=True) as records:
        timing.timing_facts(source_sha="b" * 40)
        with (
            pytest.raises(ValueError),
            timing.start_step(
                "fleet_readers_items", heartbeat=True, record_count=9
            ) as progress,
        ):
            assert reported.wait(1)
            progress["completed_count"] = 4
            raise ValueError("bad record")
    running = next(row for row in records if row["phase"] == "running")
    assert running["outcome"] == "pending" and running["record_count"] == 9
    assert running["run_id"] == "run-copy" and running["source_sha"] == "b" * 40
    assert records[-1]["outcome"] == "failed" and records[-1]["completed_count"] == 4


@pytest.mark.parametrize("named", [True, False])
def test_failed_step_records_refusal_code_or_exception_type(monkeypatch, named):
    from yoke_core.domain.deployment_run_contained_items import (
        CandidateContainmentRefusal,
    )

    monkeypatch.setattr(timing, "_transport", lambda: "https")
    exc = (
        CandidateContainmentRefusal(
            "candidate_containment_attestation_stale", "changed", "retry"
        )
        if named
        else ValueError("broken")
    )
    with timing.timing_scope("run-timing", collect=True) as records:
        with pytest.raises(type(exc)), timing.start_step("executing_stamp"):
            raise exc
    assert records[-1]["outcome"] == "failed"
    assert records[-1]["reason_code"] == (exc.code if named else "ValueError")
