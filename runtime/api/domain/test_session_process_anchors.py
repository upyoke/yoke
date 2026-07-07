"""Unit tests for the hook-written session process-anchor registry.

Every test pins ``YOKE_MACHINE_HOME`` to a tmp dir (the registry lives
under the machine home) and injects synthetic anchors / process-table
lookups, so nothing touches the real ``~/.yoke`` or the live process
tree.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts import session_identity
from yoke_contracts.process_ancestry import ProcessAnchor

from yoke_core.domain import session_process_anchors as anchors


_START = "Wed Jun 10 14:05:41 2026"


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _anchor(pid=200, start=_START, name="claude"):
    return ProcessAnchor(pid=pid, start_time=start, process_name=name)


def _record_for(home, pid):
    path = home / anchors.ANCHORS_DIR_NAME / f"{pid}.json"
    with path.open() as handle:
        return json.load(handle)


class TestRecordSessionAnchor:
    def test_writes_full_record(self, machine_home):
        record = anchors.record_session_anchor(
            "sess-1", transcript_path="/t/x.jsonl", anchor=_anchor(),
        )
        assert record is not None
        on_disk = _record_for(machine_home, 200)
        assert on_disk["session_id"] == "sess-1"
        assert on_disk["transcript_path"] == "/t/x.jsonl"
        assert on_disk["anchor_pid"] == 200
        assert on_disk["anchor_start_time"] == _START
        assert on_disk["anchor_process_name"] == "claude"
        assert on_disk["registered_at"]

    def test_rewrite_same_pid_last_writer_wins(self, machine_home):
        anchors.record_session_anchor("sess-old", anchor=_anchor())
        anchors.record_session_anchor("sess-new", anchor=_anchor())
        assert _record_for(machine_home, 200)["session_id"] == "sess-new"

    def test_no_harness_ancestor_returns_none(self, machine_home, monkeypatch):
        monkeypatch.setattr(
            session_identity,
            "find_nearest_harness_anchor",
            lambda _pid=None: None,
        )
        assert anchors.record_session_anchor("sess-1") is None
        assert not (machine_home / anchors.ANCHORS_DIR_NAME).exists()

    def test_empty_session_id_refused(self, machine_home):
        assert anchors.record_session_anchor("", anchor=_anchor()) is None

    def test_write_failure_returns_none(self, machine_home, monkeypatch):
        def _boom(_path, _data):
            raise OSError("disk full")

        monkeypatch.setattr(session_identity, "_dump_json", _boom)
        assert anchors.record_session_anchor("sess-1", anchor=_anchor()) is None


class TestResolveSessionFromAncestry:
    def test_resolves_via_live_ancestor(self, machine_home):
        anchors.record_session_anchor("sess-1", anchor=_anchor(pid=200))
        resolved = anchors.resolve_session_from_ancestry(
            400,
            parents={400: 300, 300: 200, 200: 1},
            start_time_of=lambda pid: _START if pid == 200 else "other",
        )
        assert resolved == "sess-1"

    def test_nearest_anchor_wins_for_nested_sessions(self, machine_home):
        anchors.record_session_anchor("outer", anchor=_anchor(pid=100, start="s100"))
        anchors.record_session_anchor("inner", anchor=_anchor(pid=200, start="s200"))
        resolved = anchors.resolve_session_from_ancestry(
            400,
            parents={400: 200, 200: 100, 100: 1},
            start_time_of={100: "s100", 200: "s200"}.get,
        )
        assert resolved == "inner"

    def test_pid_reuse_is_rejected_and_pruned(self, machine_home):
        anchors.record_session_anchor("sess-stale", anchor=_anchor(pid=200))
        resolved = anchors.resolve_session_from_ancestry(
            400,
            parents={400: 200, 200: 1},
            start_time_of=lambda _pid: "Thu Jun 11 09:00:00 2026",  # reused pid
        )
        assert resolved is None
        registry = machine_home / anchors.ANCHORS_DIR_NAME
        assert not (registry / "200.json").exists()

    def test_no_registry_dir_resolves_none_without_walking(
        self, machine_home, monkeypatch
    ):
        def _boom(*_a, **_k):
            raise AssertionError("process table must not be consulted")

        monkeypatch.setattr(session_identity, "ancestor_pids", _boom)
        assert anchors.resolve_session_from_ancestry(400) is None

    def test_unrelated_anchor_does_not_resolve(self, machine_home):
        anchors.record_session_anchor("sess-other", anchor=_anchor(pid=555))
        resolved = anchors.resolve_session_from_ancestry(
            400,
            parents={400: 300, 300: 1},
            start_time_of=lambda _pid: _START,
        )
        assert resolved is None

    def test_corrupt_record_is_pruned_and_skipped(self, machine_home):
        registry = machine_home / anchors.ANCHORS_DIR_NAME
        registry.mkdir(parents=True)
        (registry / "200.json").write_text("{not json", encoding="utf-8")
        resolved = anchors.resolve_session_from_ancestry(
            400,
            parents={400: 200, 200: 1},
            start_time_of=lambda _pid: _START,
        )
        assert resolved is None
        assert not (registry / "200.json").exists()

    def test_parallel_sessions_anchor_to_distinct_pids(self, machine_home):
        anchors.record_session_anchor("sess-a", anchor=_anchor(pid=201, start="sa"))
        anchors.record_session_anchor("sess-b", anchor=_anchor(pid=202, start="sb"))
        starts = {201: "sa", 202: "sb"}.get
        shell_a = anchors.resolve_session_from_ancestry(
            401, parents={401: 201, 201: 1}, start_time_of=starts,
        )
        shell_b = anchors.resolve_session_from_ancestry(
            402, parents={402: 202, 202: 1}, start_time_of=starts,
        )
        assert (shell_a, shell_b) == ("sess-a", "sess-b")


class TestPruneStaleAnchors:
    def test_prune_keeps_live_and_removes_dead(self, machine_home):
        anchors.record_session_anchor("live", anchor=_anchor(pid=201, start="sa"))
        anchors.record_session_anchor("dead", anchor=_anchor(pid=202, start="sb"))
        removed = anchors.prune_stale_anchors(
            start_time_of={201: "sa", 202: "reused"}.get,
        )
        assert removed == 1
        registry = machine_home / anchors.ANCHORS_DIR_NAME
        assert (registry / "201.json").exists()
        assert not (registry / "202.json").exists()

    def test_prune_failure_never_raises(self, machine_home, monkeypatch):
        anchors.record_session_anchor("live", anchor=_anchor(pid=201, start="sa"))

        def _boom(_pid):
            raise RuntimeError("ps exploded")

        assert anchors.prune_stale_anchors(start_time_of=_boom) == 0
