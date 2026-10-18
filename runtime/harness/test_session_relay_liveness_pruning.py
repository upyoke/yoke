"""Reporting and cleanup observe one process identity; groups retain custody."""

import json

import pytest

from yoke_harness import session_relay_record_pruning as pruning
from yoke_harness import session_process_custody as custody
from yoke_harness.session_relay_process_liveness import VerifiedDeadSession


@pytest.mark.parametrize("source", ["launch", "anchor"])
@pytest.mark.parametrize("current_start", [None, "reused", "recorded", "unresolved"])
def test_ungrouped_cleanup_uses_the_reports_resolver(
    tmp_path, monkeypatch, source, current_start
):
    record = (
        {"pid": 4002, "process_start_time": "recorded"}
        if source == "launch"
        else {"anchor_pid": 4002, "anchor_start_time": "recorded"}
    )
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record))
    observed = []

    def start_time_of(pid):
        observed.append(pid)
        if current_start == "unresolved":
            raise OSError("identity observation unavailable")
        return current_start

    def unexpected_machine_read(*_args):
        pytest.fail("ungrouped cleanup consulted the real machine's custody")

    monkeypatch.setattr(custody, "process_start_time", unexpected_machine_read)
    monkeypatch.setattr(custody.os, "kill", unexpected_machine_read)
    pruning.prune_dead_session_records(
        (VerifiedDeadSession("session", {}, (path,)),),
        start_time_of=start_time_of,
        custody_state_of=custody.custody_state,
    )
    assert observed == [4002]
    assert path.exists() == (current_start in {"recorded", "unresolved"})


@pytest.mark.parametrize("group_state", ["live", "unresolved", "gone"])
def test_group_cleanup_preserves_surviving_or_unresolved_custody(
    tmp_path, monkeypatch, group_state
):
    record = {"pid": 4002, "process_start_time": "recorded", "process_group_id": 4002}
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record))
    members = {
        "live": {"4002": "recorded"},
        "unresolved": {"4002": "reused"},
        "gone": {},
    }
    monkeypatch.setattr(custody, "group_members", lambda group: members[group_state])

    def unexpected_leader_probe(_pid):
        pytest.fail("a missing leader cannot prove that its group is gone")

    pruning.prune_dead_session_records(
        (VerifiedDeadSession("session", {}, (path,)),),
        start_time_of=unexpected_leader_probe,
        custody_state_of=custody.custody_state,
    )
    assert path.exists() == (group_state != "gone")
