"""The Inbox composes its gates for the page, not once per gate.

Each gate row is assembled from four tables, and the surfaces that consult
it — the authority predicate, the decider list, the reader's own answer —
used to re-read the same rows again. Counting statements is how "the cost
follows the number of tables, not the number of gates" stays true.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.decision_answers import (
    decision_by_actor,
    decisions_for_requests,
    list_decisions,
)
from yoke_core.domain.actor_decision_queue import pending_requests_for_actor
from yoke_core.domain.decision_request_rows import request_row, request_rows
from yoke_core.domain.decision_requests import RoleAuthority, create_decision_request


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def _gate(conn, item_id: int):
    request, _created = create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key=f"{item_id}:reviewing-implementation",
        project_id=10,
        originator_actor_id=1,
        role_authorities=[RoleAuthority("project", 10, "owner")],
        named_actor_ids=[3],
        subject_context={
            "item_id": item_id,
            "item_ref": f"YOK-{item_id}",
            "item_title": "gate subject",
            "from_stage": "reviewing-implementation",
            "to_stage": "reviewing-implementation",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "branch_changes": {
                "branch": None,
                "commit_sha": None,
                "touched_files": [],
                "summary": "No implementation branch is recorded.",
            },
            "approval_source": {
                "kind": "workflow_approval_default",
                "entry": "approval_defaults.reviewing-implementation",
            },
            "title": "gate subject",
        },
    )
    return request


def _table_reads(counting: CountingConnection, table: str) -> int:
    return sum(
        count
        for sql, count in counting.statements.items()
        if sql.startswith("SELECT") and table in sql
    )


class TestGateComposition:
    def test_composing_many_gates_reads_each_table_once(self, conn):
        ids = [_gate(conn, item_id)["id"] for item_id in (2001, 2002, 2003, 2004)]
        counting = CountingConnection(conn)

        composed = request_rows(counting, ids)

        assert set(composed) == set(ids)
        for table in (
            "FROM decision_requests",
            "decision_request_role_authorities",
            "decision_request_actor_authorities",
            "decision_request_decisions",
        ):
            assert _table_reads(counting, table) == 1, table

    def test_the_single_form_matches_the_set_form(self, conn):
        request = _gate(conn, 2011)

        assert request_row(conn, request["id"]) == request_rows(
            conn, [request["id"]]
        )[request["id"]]

    def test_an_unknown_request_still_refuses_by_name(self, conn):
        with pytest.raises(LookupError):
            request_row(conn, 987_654)

    def test_pending_page_cost_does_not_grow_per_gate_composition(self, conn):
        for item_id in (2101, 2102, 2103):
            _gate(conn, item_id)
        counting = CountingConnection(conn)

        pending = pending_requests_for_actor(counting, 3)

        assert len(pending) == 3
        # Three gates, still one composition read per table. The named-actor
        # table is deliberately not in this list: what the page asks of it is
        # per reader and per gate — whether this actor is a person the gate
        # named — rather than the gate's own membership, which composition
        # already carries.
        for table in (
            "decision_request_role_authorities",
            "decision_request_decisions",
        ):
            assert _table_reads(counting, table) == 1, table


class TestDecisionAnswerReads:
    def test_answers_for_a_set_cost_one_statement(self, conn):
        ids = [_gate(conn, item_id)["id"] for item_id in (2201, 2202)]
        counting = CountingConnection(conn)

        answers = decisions_for_requests(counting, ids)

        assert answers == {}
        assert counting.count == 1

    def test_single_form_matches_the_set_form(self, conn):
        request = _gate(conn, 2211)

        assert list_decisions(conn, request["id"]) == decisions_for_requests(
            conn, [request["id"]]
        ).get(request["id"], [])

    def test_an_actor_answer_is_found_among_answers_already_read(self):
        answers = [
            {"actor_id": 3, "action": "approve"},
            {"actor_id": 4, "action": "reject"},
        ]

        assert decision_by_actor(answers, 4) == {"actor_id": 4, "action": "reject"}
        assert decision_by_actor(answers, 9) is None
