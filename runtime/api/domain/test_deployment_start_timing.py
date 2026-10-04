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
