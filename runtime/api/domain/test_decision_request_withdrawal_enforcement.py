"""Authority and ended-subject enforcement for decision withdrawal."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.decision_requests import create_decision_request
from yoke_core.domain.decision_request_resolution import (
    withdraw_decision_request,
)
from yoke_core.domain.handlers import inbox_decisions


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


def _request(
    conn,
    *,
    kind: str,
    subject_type: str,
    subject_key: str,
    subject_context: dict,
    actor_id: int = 2,
):
    project_scope = kind != "machine_approval"
    return create_decision_request(
        conn,
        kind=kind,
        subject_type=subject_type,
        subject_key=subject_key,
        project_id=10 if project_scope else None,
        org_id=None if project_scope else 1,
        named_actor_ids=[actor_id],
        subject_context=subject_context,
        created_at="2026-07-28T12:00:00Z",
    )[0]


def _seed_item(conn) -> None:
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, title, status, workflow_id, workflow_version_id) "
        "VALUES (42, 10, 'Item', 'implementing', 'issue', 1)"
    )


def _lifecycle_request(conn, *, actor_id: int = 2):
    _seed_item(conn)
    return _request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key="42:reviewing-implementation",
        subject_context={
            "item_id": 42,
            "from_stage": "implementing",
            "transition": "reviewing-implementation",
            "workflow_id": "issue",
            "workflow_version_id": 1,
        },
        actor_id=actor_id,
    )


def test_withdraw_requires_a_bound_actor_before_database_access() -> None:
    outcome = inbox_decisions.handle_decision_withdraw(
        FunctionCallRequest(
            function="decision_requests.withdraw",
            actor=ActorContext(actor_id=None, session_id=""),
            target=TargetRef(kind="global"),
            payload={"request_id": 1, "reason": "subject ended"},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "actor_required"


def test_withdraw_handler_maps_live_authority_denial(monkeypatch) -> None:
    from yoke_core.domain import db_helpers, decision_request_resolution

    class Connection:
        rolled_back = False
        closed = False

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(db_helpers, "connect", lambda: connection)

    def deny(*_args, **_kwargs):
        raise PermissionError("actor 4 is not authorized")

    monkeypatch.setattr(
        decision_request_resolution,
        "withdraw_decision_request",
        deny,
    )
    outcome = inbox_decisions.handle_decision_withdraw(
        FunctionCallRequest(
            function="decision_requests.withdraw",
            actor=ActorContext(actor_id="4", session_id="browser"),
            target=TargetRef(kind="global"),
            payload={"request_id": 1, "reason": "subject ended"},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "permission_denied"
    assert connection.rolled_back is True
    assert connection.closed is True


def test_withdraw_requires_live_request_authority(conn) -> None:
    request = _lifecycle_request(conn, actor_id=3)
    conn.execute("UPDATE items SET status = 'cancelled' WHERE id = 42")

    with pytest.raises(PermissionError, match="not authorized to withdraw"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="item cancelled",
        )

    status = conn.execute(
        "SELECT status FROM decision_requests WHERE id = ?",
        (request["id"],),
    ).fetchone()[0]
    assert status == "pending"


def test_lifecycle_withdraw_requires_snapshot_to_end(conn) -> None:
    request = _lifecycle_request(conn)
    with pytest.raises(ValueError, match="subject has not ended"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="not needed",
        )

    conn.execute("UPDATE items SET status = 'cancelled' WHERE id = 42")
    withdrawn = withdraw_decision_request(
        conn,
        request["id"],
        actor_id=2,
        reason="item cancelled",
    )
    assert withdrawn["status"] == "withdrawn"


def test_deployment_withdraw_requires_run_stage_to_end(conn) -> None:
    conn.execute(
        "CREATE TABLE deployment_runs "
        "(id TEXT PRIMARY KEY, status TEXT, current_stage TEXT)"
    )
    conn.execute(
        "INSERT INTO deployment_runs VALUES ('run-1', 'executing', 'production')"
    )
    request = _request(
        conn,
        kind="deployment_stage_approval",
        subject_type="deployment_stage",
        subject_key="run-1:production",
        subject_context={"run_id": "run-1", "stage": "production"},
    )
    with pytest.raises(ValueError, match="subject has not ended"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="still waiting",
        )

    conn.execute("UPDATE deployment_runs SET status = 'cancelled' WHERE id = 'run-1'")
    assert (
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="run cancelled",
        )["status"]
        == "withdrawn"
    )


def test_qa_withdraw_requires_conclusive_or_waived_requirement(conn) -> None:
    conn.executescript("""
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            waived_at TEXT
        );
        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER,
            verdict TEXT,
            case_outcome TEXT
        );
        INSERT INTO qa_requirements VALUES (7, NULL);
    """)
    request = _request(
        conn,
        kind="qa_needs_review",
        subject_type="qa_requirement",
        subject_key="7",
        subject_context={"requirement_id": 7, "run_id": 70},
    )
    with pytest.raises(ValueError, match="subject has not ended"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="still inconclusive",
        )

    conn.execute("INSERT INTO qa_runs VALUES (71, 7, 'pass', 'passed')")
    assert (
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="later evidence passed",
        )["status"]
        == "withdrawn"
    )


def test_machine_expiry_is_withdrawn_explicitly_and_audited(conn) -> None:
    request = _request(
        conn,
        kind="machine_approval",
        subject_type="machine_auth_request",
        subject_key="machine-request-1",
        subject_context={"expires_at": "2026-07-28T13:00:00Z"},
    )
    with pytest.raises(ValueError, match="subject has not ended"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="not expired",
            withdrawn_at="2026-07-28T12:30:00Z",
        )

    withdrawn = withdraw_decision_request(
        conn,
        request["id"],
        actor_id=2,
        reason="device code expired",
        withdrawn_at="2026-07-28T13:00:00Z",
    )
    assert withdrawn["status"] == "withdrawn"
    event = conn.execute(
        "SELECT actor_id, envelope FROM events "
        "WHERE event_name = 'DecisionRequestWithdrawn'"
    ).fetchone()
    assert event[0] == 2
    context = json.loads(event[1])["context"]
    assert context["reason"] == "device code expired"
    assert "expired at" in context["subject_end_evidence"]


def test_strategy_withdraw_requires_revision_to_end(conn) -> None:
    conn.executescript("""
        CREATE TABLE strategy_docs (
            project_id INTEGER,
            slug TEXT,
            archived_at TEXT
        );
        CREATE TABLE strategy_doc_revisions (
            project_id INTEGER,
            slug TEXT,
            revision INTEGER
        );
        INSERT INTO strategy_docs VALUES (10, 'VISION', NULL);
        INSERT INTO strategy_doc_revisions VALUES (10, 'VISION', 1);
    """)
    request = _request(
        conn,
        kind="strategy_revision_review",
        subject_type="strategy_doc_revision",
        subject_key="10:VISION:1",
        subject_context={"slug": "VISION", "revision": 1},
    )
    with pytest.raises(ValueError, match="subject has not ended"):
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="still current",
        )

    conn.execute("INSERT INTO strategy_doc_revisions VALUES (10, 'VISION', 2)")
    assert (
        withdraw_decision_request(
            conn,
            request["id"],
            actor_id=2,
            reason="revision superseded",
        )["status"]
        == "withdrawn"
    )
