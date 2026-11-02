"""A CLEAN queue read can precede GitHub recording the merge."""

from dataclasses import replace

from runtime.api.domain.merge_queue_observer_test_helpers import (
    MERGED,
    NOT_QUEUED,
    ejected_message_id,
    landed_message_id,
    message_body,
    message_count,
    observe,
    observer_connection,
)
from yoke_core.domain import merge_queue_landing_observation
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_record_state import LANDED, STALLED


CLEAN = replace(MERGED, merged=False, closed=False, merge_state_status="CLEAN",
                merged_at=None, merge_commit_sha="")


def _observe_clean(conn, monkeypatch, second):
    sleeps = []
    reads = []
    states = iter((CLEAN, second))
    monkeypatch.setattr(merge_queue_landing_observation.time, "sleep", sleeps.append)

    def read_state(_ctx, _pr):
        reads.append(True)
        return next(states), None

    result = observe(
        conn,
        read_state=read_state,
        read_membership=lambda _ctx, _pr: (NOT_QUEUED, None),
        read_checks=lambda _ctx, _pr: ((), None),
    )
    assert len(reads) == 2
    assert sleeps == [3.0]
    assert message_count(conn) == 1
    return result


def test_clean_pull_request_that_merges_on_confirmation_never_sends_stopped_notice(monkeypatch):
    conn = observer_connection()
    result = _observe_clean(conn, monkeypatch, MERGED)

    assert result["landed"] == 1
    assert result["ejected"] == 0
    assert "Landing stopped" not in message_body(conn, landed_message_id(conn))
    assert read_landing_record(conn, 101).state == LANDED


def test_clean_pull_request_still_unheld_on_confirmation_sends_stopped_notice(monkeypatch):
    conn = observer_connection()
    result = _observe_clean(conn, monkeypatch, CLEAN)

    assert result["landed"] == 0
    assert result["ejected"] == 1
    assert "Landing stopped" in message_body(conn, ejected_message_id(conn))
    assert read_landing_record(conn, 101).state == STALLED
