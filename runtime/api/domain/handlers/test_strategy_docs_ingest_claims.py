"""Foreign-claim refusal + permission-key tests for ``strategy.ingest.run``.

Split from ``test_strategy_docs_ingest.py`` (authored-file line cap);
shared seeds/builders live in ``_strategy_docs_test_helpers``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs as doc_handlers
from yoke_core.domain.handlers import strategy_docs_ingest as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    SESSION_WITH_CLAIM,
    SESSION_WITHOUT_CLAIM,
    build_request,
    edit_rendered_body,
    ingest_files_payload,
    ok_emit,
    seed_docs,
    seed_process_claim,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


@pytest.fixture
def checkout(tmp_db: str, tmp_path: Path) -> Path:
    conn = connect_test_db(tmp_db)
    try:
        seed_docs(conn)
    finally:
        conn.close()
    root = tmp_path / "checkout"
    sd.render_docs(target_root=root, project_id=PROJECT_ID)
    return root


def _ingest_request(payload: dict, session_id: str = SESSION_WITHOUT_CLAIM):
    return build_request(
        "strategy.ingest.run", payload, session_id=session_id, actor_id="42",
    )


class TestForeignClaimRefusal:
    def _claim_held_by(self, tmp_db: str, session_id: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_session(conn, session_id)
            seed_process_claim(conn, session_id)
        finally:
            conn.close()

    def test_terminal_session_may_ingest_without_live_claim(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit.\n")
        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_ingest(
                _ingest_request(
                    ingest_files_payload(checkout, ["PAD"]),
                    session_id="",
                )
            )
        assert outcome.primary_success is True
        assert outcome.result_payload["docs"][0]["status"] == "written"
        emit.assert_called_once()
        assert emit.call_args.kwargs["session_id"] == ""

    def test_bounces_when_another_session_holds_the_claim(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        self._claim_held_by(tmp_db, SESSION_WITH_CLAIM)
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit.\n")
        outcome = handlers.handle_ingest(
            _ingest_request(
                ingest_files_payload(checkout, ["PAD"]),
                session_id=SESSION_WITHOUT_CLAIM,
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "ingest_blocked_by_live_process_claim"
        assert SESSION_WITH_CLAIM in outcome.error.message
        conn = connect_test_db(tmp_db)
        try:
            row = conn.execute(
                f"SELECT updated_at FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_ID, "PAD"),
            ).fetchone()
        finally:
            conn.close()
        assert str(row["updated_at"]) == SEED_UPDATED_AT

    def test_terminal_session_bounces_when_any_session_holds_claim(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        self._claim_held_by(tmp_db, SESSION_WITH_CLAIM)
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit.\n")
        outcome = handlers.handle_ingest(
            _ingest_request(
                ingest_files_payload(checkout, ["PAD"]),
                session_id="",
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "ingest_blocked_by_live_process_claim"
        assert SESSION_WITH_CLAIM in outcome.error.message

    def test_claim_holder_session_may_ingest(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        self._claim_held_by(tmp_db, SESSION_WITH_CLAIM)
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit.\n")
        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ):
            outcome = handlers.handle_ingest(
                _ingest_request(
                    ingest_files_payload(checkout, ["PAD"]),
                    session_id=SESSION_WITH_CLAIM,
                )
            )
        assert outcome.primary_success is True
        assert outcome.result_payload["docs"][0]["status"] == "written"

    def test_dry_run_previews_under_a_foreign_claim(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        self._claim_held_by(tmp_db, SESSION_WITH_CLAIM)
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "Edit.\n")
        outcome = handlers.handle_ingest(
            _ingest_request(
                ingest_files_payload(checkout, ["PAD"], dry_run=True),
                session_id=SESSION_WITHOUT_CLAIM,
            )
        )
        assert outcome.primary_success is True
        assert outcome.result_payload["docs"][0]["status"] == "changed"

