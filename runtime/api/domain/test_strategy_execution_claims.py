"""Blitz execution-document linking and claim contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.backlog_mutations_test_helpers import _patch_externals
from runtime.api.domain.strategy_execution_test_support import (
    handoff_item_claim as _handoff_item_claim,
    seed_blitz_item as _seed_blitz_item,
    seed_session_claim as _seed_session_claim,
    seed_strategy_doc as _seed_doc,
    strategy_function_request as _function_request,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.handlers.strategy_doc_surfaces import (
    handle_execution_get,
    handle_execution_link,
)
from yoke_core.domain.strategy_coordination import (
    append_strategy_coordination,
    blitz_completion_evidence,
)
from yoke_core.domain.strategy_doc_surfaces import get_blitz_surface
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    acquire_strategy_doc_claim,
    authorize_strategy_doc_write,
    link_execution_document,
    release_strategy_doc_claim,
)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        yield db_path


def test_typed_blitz_create_can_be_refined_linked_and_read_for_execution(
    tmp_db: str,
) -> None:
    with _patch_externals():
        created = handle_item_create(
            _function_request(
                "items.create",
                target=TargetRef(kind="global", project_id="yoke"),
                payload={
                    "title": "Execute the delivery plan",
                    "workflow": "blitz",
                    "project": "yoke",
                    "entry_surface": "harness_skill",
                },
            ),
        )
    assert created.primary_success is True, created.error
    item_id = created.result_payload["item_id"]

    conn = connect_test_db(tmp_db)
    try:
        _seed_session_claim(conn, item_id, "refine-blitz-test")
        _seed_doc(
            conn,
            "DELIVERY-PLAN",
            "# Delivery plan\n\n"
            "## Outcomes\nShip the integrated result.\n\n"
            "## Slices\n1. Implement and verify the bounded change.\n\n"
            "## Affected areas and dependencies\nThe project source; no "
            "external dependency.\n\n"
            "## Verification and delivery\nRun focused verification and "
            "the registered delivery flow.\n\n"
            "## Unresolved decisions\nNone.\n\n"
            "## Parent strategy\nNo parent strategy document.\n",
        )
    finally:
        conn.close()

    target = TargetRef(kind="item", item_id=item_id, project_id="yoke")
    with _patch_externals():
        refining = handle_transition(
            _function_request(
                "lifecycle.transition.execute",
                target=target,
                payload={
                    "source_status": "idea",
                    "target_status": "refining-idea",
                    "reason": "Blitz refinement started",
                },
            ),
        )
    assert refining.primary_success is True, refining.error

    linked = handle_execution_link(
        _function_request(
            "strategy.execution.link",
            target=target,
            payload={"slug": "DELIVERY-PLAN"},
        ),
    )
    assert linked.primary_success is True, linked.error

    with _patch_externals():
        refined = handle_transition(
            _function_request(
                "lifecycle.transition.execute",
                target=target,
                payload={
                    "source_status": "refining-idea",
                    "target_status": "refined-idea",
                    "reason": "Blitz execution document linked and verified",
                },
            ),
        )
    assert refined.primary_success is True, refined.error

    execution_read = handle_execution_get(
        _function_request("strategy.execution.get", target=target),
    )
    assert execution_read.primary_success is True, execution_read.error
    execution = execution_read.result_payload["execution"]
    assert execution["item"]["workflow_id"] == "blitz"
    assert execution["item"]["status"] == "refined-idea"
    assert execution["execution_document"]["slug"] == "DELIVERY-PLAN"
    assert execution["execution_linked_at"]


def test_item_owned_claim_survives_session_handoff(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "LIVE-PLAN", "# Live plan\n")
        _seed_blitz_item(conn, 2001, 2001)
        _seed_session_claim(conn, 2001, "session-a")
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="LIVE-PLAN",
            actor_id=1,
            session_id="session-a",
        )
        claim = acquire_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="session-a",
            actor_id=1,
        )
        appended = append_strategy_coordination(
            conn,
            project_id=1,
            slug="LIVE-PLAN",
            section="Slice Log",
            entry="- worker session landed a committed slice",
            actor_id=None,
            session_id="worker-session",
        )
        assert authorize_strategy_doc_write(
            conn,
            project_id=1,
            slug="LIVE-PLAN",
            session_id="session-a",
        )
        _handoff_item_claim(conn, 2001, "session-a", "session-b")
        with pytest.raises(StrategyDocClaimAuthorizationError):
            authorize_strategy_doc_write(
                conn,
                project_id=1,
                slug="LIVE-PLAN",
                session_id="session-a",
            )
        assert authorize_strategy_doc_write(
            conn,
            project_id=1,
            slug="LIVE-PLAN",
            session_id="session-b",
        )
        surface = get_blitz_surface(conn, 2001)
        released = release_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="session-b",
            actor_id=1,
            reason="completed",
        )
    finally:
        conn.close()

    assert claim["owning_item_id"] == 2001
    assert claim["workflow_id"] == "blitz"
    assert int(claim["workflow_version_id"]) > 0
    assert appended["revision"] == 2
    assert surface["execution_document"]["revisions"][0]["session_id"] == (
        "worker-session"
    )
    assert surface["execution_document"]["slug"] == "LIVE-PLAN"
    assert "worker session landed" in surface["execution_document"]["content"]
    assert surface["item_claim"]["session_id"] == "session-b"
    assert released["release_mode"] == "normal"


def test_second_blitz_cannot_claim_same_document(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "SHARED-PLAN", "# Shared plan\n")
        for item_id, session_id in ((2001, "session-a"), (2002, "session-b")):
            _seed_blitz_item(conn, item_id, item_id)
            _seed_session_claim(conn, item_id, session_id)
            link_execution_document(
                conn,
                item_id=item_id,
                project_id=1,
                slug="SHARED-PLAN",
                actor_id=1,
                session_id=session_id,
            )
        acquire_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="session-a",
            actor_id=1,
        )
        with pytest.raises(StrategyDocClaimConflictError, match="item 2001"):
            acquire_strategy_doc_claim(
                conn,
                item_id=2002,
                session_id="session-b",
                actor_id=1,
            )
    finally:
        conn.close()


def test_break_glass_release_requires_reason(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "STRANDED", "# Stranded\n")
        _seed_blitz_item(conn, 2001, 2001)
        _seed_session_claim(conn, 2001, "session-a")
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="STRANDED",
            actor_id=1,
            session_id="session-a",
        )
        acquire_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="session-a",
            actor_id=1,
        )
        with pytest.raises(StrategyDocClaimAuthorizationError, match="reason"):
            release_strategy_doc_claim(
                conn,
                item_id=2001,
                session_id="operator",
                actor_id=9,
                break_glass=True,
            )
        result = release_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="operator",
            actor_id=9,
            break_glass=True,
            reason="holder machine was lost",
        )
    finally:
        conn.close()
    assert result["release_mode"] == "break_glass"


def test_blitz_completion_evidence_stays_in_the_document(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(
            conn,
            "CLOSEOUT",
            "# Closeout\n\n## Completion and parent reconciliation\n\n"
            "Completed the work. Verification evidence is recorded. "
            "No remaining work; the parent was reconciled.\n",
        )
        _seed_blitz_item(conn, 2001, 2001)
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="CLOSEOUT",
            actor_id=1,
            session_id="session-a",
        )
        evidence = blitz_completion_evidence(conn, 2001)
    finally:
        conn.close()
    assert evidence["satisfied"] is True
    assert evidence["missing"] == []
