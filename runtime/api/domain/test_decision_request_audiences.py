"""Requests share live audience targeting without changing approval policy."""

from runtime.api.domain.decision_request_test_support import decision_request_connection
from runtime.api.domain.decision_request_test_support import transition_request
from yoke_core.domain import audiences
from yoke_core.domain.approval_decisions import evaluate_decisions
from yoke_core.domain.decision_request_rows import request_row
from yoke_core.domain.decision_request_authority import authority_reason


def test_request_storage_and_role_change_share_audience_resolver():
    with decision_request_connection() as conn:
        request, _ = transition_request(conn)
        assert request["audience_id"]
        assert (
            len(
                audiences.rules_for_audiences(conn, [request["audience_id"]])[
                    request["audience_id"]
                ]
            )
            == 4
        )
        conn.execute("INSERT INTO actor_project_roles VALUES (4, 10, 2, 'later')")
        assert audiences.includes_actor(conn, request["audience_id"], 4)
        assert authority_reason(conn, request["id"], 4) == "project operator"
        conn.execute("DELETE FROM actor_project_roles WHERE actor_id=4 AND role_id=2")
        assert authority_reason(conn, request["id"], 4) is None
        conn.execute("UPDATE actors SET status='retired' WHERE id=3")
        assert authority_reason(conn, request["id"], 3) is None


def test_all_mode_counts_rules_and_any_mode_counts_one():
    with decision_request_connection() as conn:
        request, _ = transition_request(conn)
        request["approval_mode"] = "all"
        one_answer = [{"actor_id": 2, "action": "approve", "note": None}]
        progress = evaluate_decisions(conn, request, decisions=one_answer)
        assert (
            progress.required == 4 and progress.satisfied == 1 and not progress.resolved
        )
        conn.execute("INSERT INTO actor_project_roles VALUES (2, 10, 2, 'later')")
        assert evaluate_decisions(conn, request, decisions=one_answer).satisfied == 2
        answers = one_answer + [
            {"actor_id": actor, "action": "approve", "note": None} for actor in (3, 5)
        ]
        assert evaluate_decisions(conn, request, decisions=answers).resolved
        request["approval_mode"] = "any"
        assert evaluate_decisions(conn, request, decisions=one_answer).resolved
        assert request_row(conn, request["id"])["audience_id"] == request["audience_id"]


def test_named_audience_id_and_inline_rules_are_exclusive():
    import pytest
    from runtime.api.domain.test_decision_request_operator_question import filing
    from yoke_core.domain.decision_requests import create_decision_request

    with decision_request_connection() as value:
        value.executescript("""
            CREATE TABLE harness_sessions (session_id TEXT, actor_id INTEGER,
                ended_at TEXT, terminated_at TEXT);
            INSERT INTO harness_sessions VALUES ('worker', 2, NULL, NULL);
        """)
        audience_id = audiences.create_audience(
            value, project_id=10, rules=[{"scope_kind": "actor", "scope_id": 3}]
        )
        for overrides in ({}, {"role_authorities": [], "named_actor_ids": [3]}):
            with pytest.raises(ValueError, match="exclusive"):
                create_decision_request(
                    value, **filing(audience_id=audience_id, **overrides)
                )
