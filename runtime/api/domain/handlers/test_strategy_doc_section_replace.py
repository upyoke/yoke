"""``strategy.doc.section_replace``: one section moves, the rest does not.

The write itself is the whole-document path's, so these cover what is new:
the section splice reaching the stored row, the compare-and-swap that keeps
a stale caller from rebasing its section onto content it never saw, a
heading the document lacks, and the same process-claim gate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    SEED_UPDATED_AT,
    SESSION_WITHOUT_CLAIM,
    SESSION_WITH_CLAIM,
    build_request,
    ok_emit,
    seed_docs,
    seed_process_claim,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


SLUG = "MISSION"
#: The tail carries most of the bytes, so replacing it is what the shrink
#: guard is there to catch; replacing the short status section is not.
TAIL = "Tail that must survive.\n" * 20
SECTIONED = (
    "# MISSION\n\nIntro that must survive.\n\n"
    "## Live status\n\nStale status line.\nAnother stale line.\n\n"
    f"## Next up\n\n{TAIL}"
)
FRESH = "Fresh status line.\nA second fresh line, keeping the byte count up.\n"


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _seed_sectioned(tmp_db: str, *, with_claim: bool = True) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_docs(conn)
        conn.execute(
            f"UPDATE {sd.STRATEGY_DOCS_TABLE} SET content = %s "
            "WHERE project_id = %s AND slug = %s",
            (SECTIONED, PROJECT_ID, SLUG),
        )
        conn.commit()
        session = SESSION_WITH_CLAIM if with_claim else SESSION_WITHOUT_CLAIM
        seed_session(conn, session)
        if with_claim:
            seed_process_claim(conn, SESSION_WITH_CLAIM)
    finally:
        conn.close()


def _stored_content(tmp_db: str) -> str:
    conn = connect_test_db(tmp_db)
    try:
        row = conn.execute(
            f"SELECT content FROM {sd.STRATEGY_DOCS_TABLE} "
            "WHERE project_id = %s AND slug = %s",
            (PROJECT_ID, SLUG),
        ).fetchone()
    finally:
        conn.close()
    return str(row["content"])


def _call(payload: dict, *, session_id: str = SESSION_WITH_CLAIM):
    with patch.object(handlers._events, "emit_event", return_value=ok_emit()) as emit:
        outcome = handlers.handle_doc_section_replace(
            build_request(
                "strategy.doc.section_replace",
                payload,
                session_id=session_id,
                actor_id="7",
            )
        )
    return outcome, emit


def test_only_the_named_section_changes_in_the_stored_row(tmp_db: str) -> None:
    _seed_sectioned(tmp_db)

    outcome, emit = _call(
        {
            "slug": SLUG,
            "heading": "Live status",
            "content": FRESH,
            "base_updated_at": SEED_UPDATED_AT,
        }
    )

    assert outcome.primary_success is True
    stored = _stored_content(tmp_db)
    assert "Intro that must survive." in stored
    assert TAIL.strip() in stored
    assert "Fresh status line." in stored
    assert "Stale status line." not in stored
    assert stored.count("## Live status") == 1
    emit.assert_called_once()
    assert emit.call_args.kwargs["context"]["source"] == "section_replace"


def test_a_base_the_row_has_moved_past_refuses_instead_of_rebasing(
    tmp_db: str,
) -> None:
    """The splice reads the stored body, so a stale base cannot be honoured."""
    _seed_sectioned(tmp_db)

    outcome, emit = _call(
        {
            "slug": SLUG,
            "heading": "Live status",
            "content": FRESH,
            "base_updated_at": "1999-01-01T00:00:00.000000Z",
        }
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "replace_conflict"
    assert SEED_UPDATED_AT in outcome.error.message
    assert "Stale status line." in _stored_content(tmp_db)
    emit.assert_not_called()


def test_a_heading_the_document_lacks_is_refused_and_writes_nothing(
    tmp_db: str,
) -> None:
    _seed_sectioned(tmp_db)

    outcome, emit = _call(
        {
            "slug": SLUG,
            "heading": "Live statuses",
            "content": FRESH,
            "base_updated_at": SEED_UPDATED_AT,
        }
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "unknown_section"
    assert "Live status" in outcome.error.message
    assert _stored_content(tmp_db) == SECTIONED
    emit.assert_not_called()


def test_the_process_claim_gate_is_the_one_the_replace_path_uses(
    tmp_db: str,
) -> None:
    _seed_sectioned(tmp_db, with_claim=False)

    outcome, emit = _call(
        {
            "slug": SLUG,
            "heading": "Live status",
            "content": FRESH,
            "base_updated_at": SEED_UPDATED_AT,
        },
        session_id=SESSION_WITHOUT_CLAIM,
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "strategy_claim_required"
    assert _stored_content(tmp_db) == SECTIONED
    emit.assert_not_called()


def test_shrinking_a_document_past_the_guard_still_refuses_without_force(
    tmp_db: str,
) -> None:
    """The whole-document guards apply: this composes content, it does not bypass."""
    _seed_sectioned(tmp_db)

    outcome, _emit = _call(
        {
            "slug": SLUG,
            "heading": "Next up",
            "content": "One short line.",
            "base_updated_at": SEED_UPDATED_AT,
        }
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "shrink_guard_refused"
