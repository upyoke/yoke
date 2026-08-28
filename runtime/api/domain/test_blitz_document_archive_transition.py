"""Blitz completion archives its execution document atomically."""

from __future__ import annotations

from io import StringIO

import pytest

from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import (
    backlog,
    backlog_update_op,
    blitz_document_archive,
    strategy_docs,
)
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_execution import link_execution_document


@pytest.fixture(autouse=True)
def _isolated_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )


def _seed_document(conn, slug: str, *, parent_slug: str | None = None) -> None:
    if parent_slug is not None:
        create_doc(conn, 1, parent_slug, f"# {parent_slug}\n", actor_id=1)
    create_doc(conn, 1, slug, f"# {slug}\n", actor_id=1)
    if parent_slug is not None:
        conn.execute(
            "UPDATE strategy_docs SET parent_slug=%s WHERE project_id=1 AND slug=%s",
            (parent_slug, slug),
        )
        conn.commit()


def _seed_linked_blitz(
    conn,
    *,
    item_id: int,
    slug: str,
    status: str = "reviewing-implementation",
) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="blitz",
        status=status,
    )
    link_execution_document(
        conn,
        item_id=item_id,
        project_id=1,
        slug=slug,
        actor_id=1,
        session_id="blitz-archive-test",
    )


def _complete(conn, item_id: int) -> tuple[dict, str]:
    output = StringIO()
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="done",
        done_nonce_verified=True,
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
        out=output,
    )
    return result, output.getvalue()


def _archived_at(conn, slug: str):
    return conn.execute(
        "SELECT archived_at FROM strategy_docs WHERE project_id=1 AND slug=%s",
        (slug,),
    ).fetchone()[0]


def test_done_archives_only_the_linked_document(test_db) -> None:
    _seed_document(test_db, "DELIVERY-PLAN", parent_slug="MASTER-PLAN")
    _seed_linked_blitz(test_db, item_id=4101, slug="DELIVERY-PLAN")

    result, output = _complete(test_db, 4101)

    assert result["success"] is True
    assert _archived_at(test_db, "DELIVERY-PLAN") is not None
    assert _archived_at(test_db, "MASTER-PLAN") is None
    assert "Archived execution document 'DELIVERY-PLAN'." in output


def test_already_archived_document_is_an_idempotent_noop(test_db) -> None:
    _seed_document(test_db, "ALREADY-COMPLETE")
    _seed_linked_blitz(test_db, item_id=4102, slug="ALREADY-COMPLETE")
    strategy_docs.set_doc_archived(
        test_db,
        1,
        "ALREADY-COMPLETE",
        archived=True,
    )

    result, output = _complete(test_db, 4102)

    assert result["success"] is True
    assert "Already archived execution document 'ALREADY-COMPLETE'." in output


def test_document_stays_active_for_another_live_blitz(test_db) -> None:
    _seed_document(test_db, "SHARED-PLAN")
    _seed_linked_blitz(test_db, item_id=4103, slug="SHARED-PLAN")
    _seed_linked_blitz(
        test_db,
        item_id=4104,
        slug="SHARED-PLAN",
        status="implementing",
    )

    result, output = _complete(test_db, 4103)

    assert result["success"] is True
    assert _archived_at(test_db, "SHARED-PLAN") is None
    assert (
        "Kept execution document 'SHARED-PLAN' active for live Blitz YOK-4104."
        in output
    )


def test_archive_failure_rolls_back_done_and_names_recovery(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_document(test_db, "WRITE-FAILURE")
    _seed_linked_blitz(test_db, item_id=4105, slug="WRITE-FAILURE")

    def fail_archive(*_args, **_kwargs):
        raise OSError("strategy document storage unavailable")

    monkeypatch.setattr(
        blitz_document_archive,
        "_archive_without_commit",
        fail_archive,
    )
    result, _output = _complete(test_db, 4105)

    assert result["success"] is False
    assert result["error_code"] == "GATE_BLITZ_DOCUMENT_ARCHIVE_FAILED"
    assert "the done transition was rolled back" in result["error"]
    assert "Recovery:" in result["error"]
    assert _archived_at(test_db, "WRITE-FAILURE") is None
    status = test_db.execute("SELECT status FROM items WHERE id=4105").fetchone()[0]
    assert str(status) == "reviewing-implementation"
