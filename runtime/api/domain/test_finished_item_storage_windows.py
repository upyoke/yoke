"""Finished-item cutoffs preserve native timestamp precision."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_composition_clock_filters import (
    STAMP,
    clocks as clocks,
)
from runtime.api.domain.test_deployment_clock_reads import (
    native_clocks as native_clocks,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain import item_finished_times as finished
from yoke_core.domain import item_status_transitions as transitions


@pytest.fixture
def finishers(native_clocks, monkeypatch):
    native_clocks.execute(
        "ALTER TABLE items ADD status text, ADD workflow_version_id integer"
    )
    native_clocks.execute(
        "UPDATE items SET status=CASE WHEN id=3 THEN 'implementing' ELSE 'done' END,"
        "workflow_version_id=99"
    )
    cutoff = STAMP - timedelta(hours=24)
    for item_id, value in (
        (1, format_instant(cutoff)),
        (2, format_instant(cutoff - timedelta(microseconds=1))),
        (3, "2026-03-09 02:32:26"),
    ):
        native_clocks.execute(
            "INSERT INTO item_status_transitions "
            "SELECT id,NULL,status,%s FROM items WHERE id=%s",
            (value, item_id),
        )
    monkeypatch.setattr(finished, "utc_now", lambda: STAMP)
    monkeypatch.setattr(
        finished,
        "load_frontier_workflow_versions",
        lambda _: SimpleNamespace(
            runtimes={99: SimpleNamespace(terminal_stage_ids=frozenset({"done"}))}
        ),
    )
    return native_clocks, cutoff


def test_finished_window_readers_preserve_inclusive_cutoff(finishers):
    conn, cutoff = finishers
    assert finished.finished_times_in_window(conn) == {1: cutoff}
    clause, params = finished.finished_window_clause(conn)
    assert [
        row[0]
        for row in conn.execute(
            f"SELECT i.id FROM items i WHERE {clause} ORDER BY i.id", params
        ).fetchall()
    ] == [1, 3]
    assert not isinstance(params[-1], str)


def test_transition_recorder_clock_can_be_read(finishers, monkeypatch):
    conn, cutoff = finishers
    conn.execute(
        "ALTER TABLE item_status_transitions ADD from_status text, ADD source text, "
        "ADD session_id text, ADD actor_id integer, ADD project_id integer"
    )
    monkeypatch.setattr(transitions, "utc_now", lambda: STAMP)
    monkeypatch.setattr(transitions, "_resolve_identity", lambda *_: (None, None))
    monkeypatch.setattr(transitions, "touch_item_activity", lambda *_, **__: None)
    assert transitions.record_item_transition(
        conn, item_id=3, from_status="idea", to_status="implementing", project_id=1
    )
    assert finished.finished_times_in_window(conn) == {1: cutoff, 3: STAMP}
