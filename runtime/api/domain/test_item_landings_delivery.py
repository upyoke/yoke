"""Which release delivered one landing, asked as a commit.

The per-item delivery count may short-circuit on run membership: a run that
names the item answers for the item. A landing is narrower than that. A run
that named an item before its newest merge existed did not deliver that
merge, and reporting otherwise would credit a release with shipping work it
never carried.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import item_landings_delivery as delivery
from yoke_core.domain.handlers import item_landings_ops as ops
from yoke_core.domain.item_landings import ItemLanding, append_landing
from yoke_core.domain.item_landings_schema import ROUTE_STANDALONE
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

FIRST_MERGE = "a" * 40
SECOND_MERGE = "b" * 40
ITEM_ID = 9301


class _RecordingCandidates:
    """Stands in for ReleaseCandidates, recording exactly how it was asked."""

    def __init__(self, carried):
        self.carried = carried
        self.calls = []

    def carrier_for(self, sha, *, item_id=None):
        self.calls.append((sha, item_id))
        return self.carried.get(sha)


def _ask(monkeypatch, carried):
    candidates = _RecordingCandidates(carried)
    monkeypatch.setattr(
        delivery, "ReleaseCandidates", lambda *_a, **_kw: candidates,
    )
    resolved = delivery.delivery_by_landing(
        object(),
        merge_shas=[FIRST_MERGE, SECOND_MERGE],
        project_id=1,
        environment_id=None,
        flow="",
    )
    return candidates, resolved


def test_a_landing_is_asked_as_a_commit_never_as_its_item(monkeypatch):
    """Passing the item id would credit one run with every landing."""
    candidates, _ = _ask(monkeypatch, {})

    assert [sha for sha, _ in candidates.calls] == [FIRST_MERGE, SECOND_MERGE]
    assert {item_id for _, item_id in candidates.calls} == {None}


def test_only_the_landings_a_release_carried_are_reported_delivered(monkeypatch):
    carrier = {"run_id": "run-20260919-012", "flow": "acme-prod"}
    _, resolved = _ask(monkeypatch, {FIRST_MERGE: carrier})

    assert resolved == {FIRST_MERGE: carrier}
    # Absent, not a falsy entry: the panel tells "no release carried this"
    # apart from "the question could not be asked".
    assert SECOND_MERGE not in resolved


def test_no_landings_asks_no_releases(monkeypatch):
    """An item that never landed must not resolve a project's releases."""
    def forbidden(*_a, **_kw):
        raise AssertionError("no landing means no release to ask about")

    monkeypatch.setattr(delivery, "ReleaseCandidates", forbidden)

    assert delivery.delivery_by_landing(
        object(), merge_shas=[], project_id=1, environment_id=None, flow="",
    ) == {}


def test_the_registered_read_serves_landings_oldest_first(test_db):
    """End to end through the handler, against a real database."""
    insert_item(
        test_db, id=ITEM_ID, title="Item that lands twice",
        workflow_id="dash", status="release",
    )
    for merge, when in (
        (FIRST_MERGE, "2026-09-19T03:12:00Z"),
        (SECOND_MERGE, "2026-09-19T23:02:00Z"),
    ):
        append_landing(test_db, ItemLanding(
            item_id=ITEM_ID, merge_sha=merge, candidate_sha=merge,
            target_branch="main", route=ROUTE_STANDALONE, landed_at=when,
        ))
    test_db.commit()

    outcome = ops.handle_list_item_landings(FunctionCallRequest(
        function="item_landings.list",
        actor=ActorContext(actor_id=None, session_id="s-landings"),
        target=TargetRef(kind="item", item_id=ITEM_ID),
        payload={},
    ))

    assert outcome.primary_success, outcome.error
    rows = outcome.result_payload["rows"]
    assert [row["merge_sha"] for row in rows] == [FIRST_MERGE, SECOND_MERGE]
    assert outcome.result_payload["count"] == 2
    # No release exists in this universe, so nothing carried either landing --
    # and the question was asked and answered, not skipped.
    assert outcome.result_payload["delivery_unreadable"] is False
    assert [row["delivery"] for row in rows] == [None, None]
