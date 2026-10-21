"""Delivery containment ignores releases completed before the landing."""

import sqlite3
from time import monotonic
from unittest.mock import Mock

import pytest

from yoke_core.domain import delivery_evidence_ladder as ladder
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    UNDETERMINED,
    ContainmentVerdict,
)


MERGED_AT = "2026-10-21T12:00:00Z"


@pytest.fixture
def delivery(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INTEGER, project_id INTEGER, merged_at TEXT)")
    conn.execute("INSERT INTO items VALUES (1, 7, ?)", (MERGED_AT,))
    monkeypatch.setattr(ladder, "_table_exists", lambda *_: True)
    monkeypatch.setattr(ladder, "item_merge_identity", lambda *_: "a" * 40)
    monkeypatch.setattr(ladder, "item_closing_flows", lambda *_: {"production"})
    monkeypatch.setattr(ladder, "latest_completion_run", lambda *_: None)
    containment = Mock(return_value=ContainmentVerdict(CONTAINED))
    monkeypatch.setattr(ladder, "candidate_contains_commit", containment)

    def evaluate(runs, *, flow="production"):
        monkeypatch.setattr(ladder, "item_completion_flow", lambda *_: flow)
        reader = "succeeded_flow_runs" if flow else "succeeded_persistent_runs"
        monkeypatch.setattr(ladder, reader, lambda *_, **__: runs)
        return ladder.delivery_evidence(conn, 1)

    yield conn, containment, evaluate
    conn.close()


def run(completed_at, lineage="b" * 40):
    return {"id": lineage, "release_lineage": lineage, "completed_at": completed_at}


@pytest.mark.parametrize("flow", ["production", ""])
def test_pending_member_skips_every_premerge_release(delivery, flow):
    conn, containment, evaluate = delivery
    started = monotonic()
    evidence = evaluate([run("2026-10-21T11:59:59Z")] * 10, flow=flow)
    assert monotonic() - started < 2
    assert evidence.state == ladder.NOT_DISCHARGED
    containment.assert_not_called()


@pytest.mark.parametrize("flow", ["production", ""])
@pytest.mark.parametrize(
    "completed_at",
    [MERGED_AT, "2026-10-21T12:00:01Z", "2026-10-21T08:00:00-04:00", None],
)
def test_equal_later_and_unknown_completion_keep_containment(delivery, flow, completed_at):
    _, containment, evaluate = delivery
    evidence = evaluate([run(completed_at)], flow=flow)
    assert evidence.discharged
    containment.assert_called_once()


def test_missing_merge_time_keeps_containment(delivery):
    conn, containment, evaluate = delivery
    conn.execute("UPDATE items SET merged_at = NULL")
    assert evaluate([run("2026-10-21T11:59:59Z")]).discharged
    containment.assert_called_once()


@pytest.mark.parametrize("state", [CONTAINED, NOT_CONTAINED, UNDETERMINED])
def test_eligible_release_preserves_its_verdict(delivery, state):
    conn, containment, evaluate = delivery
    containment.return_value = ContainmentVerdict(state, "unreadable", "Retry.")
    evidence = evaluate([
        run("2026-10-21T11:59:59Z", "old"),
        run(MERGED_AT, "eligible"),
    ])
    expected = {
        CONTAINED: ladder.DISCHARGED,
        NOT_CONTAINED: ladder.NOT_DISCHARGED,
        UNDETERMINED: ladder.UNDETERMINED_DELIVERY,
    }
    assert evidence.state == expected[state]
    containment.assert_called_once_with(
        conn,
        7,
        candidate_lineage="eligible",
        commit_sha="a" * 40,
    )
