"""Tests for ``strategy.doc.create``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs_create as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    PROJECT_SLUG,
    SEED_CONTENT,
    SESSION_WITHOUT_CLAIM,
    SESSION_WITH_CLAIM,
    build_request,
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


def _request(slug: str, content: str, session_id: str = SESSION_WITHOUT_CLAIM):
    return build_request(
        "strategy.doc.create",
        {"slug": slug, "content": content},
        session_id=session_id,
        actor_id="7",
    )


class TestDocCreate:
    def test_creates_new_doc_without_requiring_process_claim(
        self, tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        content = "# OPERATIONS NOTES\n\nInitial body.\n"
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_doc_create(
                _request("OPERATIONS-NOTES", content)
            )

        assert outcome.primary_success is True
        assert outcome.result_payload["project_id"] == PROJECT_ID
        assert outcome.result_payload["project_slug"] == PROJECT_SLUG
        assert outcome.result_payload["slug"] == "OPERATIONS-NOTES"
        assert outcome.result_payload["new_bytes"] == len(
            content.encode("utf-8")
        )
        emit.assert_called_once()
        assert emit.call_args.args[0] == handlers.STRATEGY_DOC_CREATED_EVENT_NAME
        assert emit.call_args.kwargs["context"]["slug"] == "OPERATIONS-NOTES"

        conn = connect_test_db(tmp_db)
        try:
            row = conn.execute(
                f"SELECT content, updated_by_actor_id FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_ID, "OPERATIONS-NOTES"),
            ).fetchone()
        finally:
            conn.close()
        assert str(row["content"]) == content
        assert int(row["updated_by_actor_id"]) == 7

    def test_terminal_session_may_create_when_no_live_claim(
        self, tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_doc_create(
                _request("OPERATIONS-NOTES", "# Operations\n", session_id="")
            )

        assert outcome.primary_success is True
        emit.assert_called_once()
        assert emit.call_args.kwargs["session_id"] == ""

    def test_duplicate_slug_is_typed_refusal(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_doc_create(
            _request("MISSION", SEED_CONTENT["MISSION"] + "extra\n")
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "doc_already_exists"
        assert "doc replace" in outcome.error.message

    def test_invalid_slug_and_empty_content_codes(self, tmp_db: str) -> None:
        invalid = handlers.handle_doc_create(
            _request("../escape", "# content\n")
        )
        empty = handlers.handle_doc_create(
            _request("EMPTY", "  \n")
        )
        assert invalid.error.code == "unknown_slug"
        assert empty.error.code == "empty_content_refused"

    def test_foreign_strategy_claim_blocks_create(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()

        outcome = handlers.handle_doc_create(
            _request("OPERATIONS-NOTES", "# Operations\n")
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "create_blocked_by_live_process_claim"
        assert SESSION_WITH_CLAIM in outcome.error.message

    def test_terminal_session_blocks_when_live_claim_exists(
        self, tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()

        outcome = handlers.handle_doc_create(
            _request("OPERATIONS-NOTES", "# Operations\n", session_id="")
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "create_blocked_by_live_process_claim"
        assert SESSION_WITH_CLAIM in outcome.error.message

    def test_claim_holder_session_may_create(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()

        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ):
            outcome = handlers.handle_doc_create(
                _request(
                    "OPERATIONS-NOTES", "# Operations\n",
                    session_id=SESSION_WITH_CLAIM,
                )
            )
        assert outcome.primary_success is True


def test_registration_shape() -> None:
    (entry,) = handlers.REGISTRATIONS
    assert entry["function_id"] == "strategy.doc.create"
    assert entry["owner_module"] == (
        "yoke_core.domain.handlers.strategy_docs_create"
    )
    assert entry["target_kinds"] == ["global"]
    assert entry["side_effects"] == ["db_write", "event_emit"]
    assert entry["emitted_event_names"] == [
        handlers.STRATEGY_DOC_CREATED_EVENT_NAME
    ]
    assert "unique_slug" in entry["guardrails"]
    assert "foreign_process_claim_refused" in entry["guardrails"]
    assert entry["ambient_session_required"] is False


def test_permission_key_matches_strategy_writes() -> None:
    from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
    from yoke_core.domain.yoke_function_permissions import (
        permission_key_for,
    )
    from yoke_core.domain.yoke_function_registry import RegistryEntry

    entry = RegistryEntry(
        function_id="strategy.doc.create",
        handler=lambda r: None,
        request_model=handlers.DocCreateRequest,
        response_model=handlers.DocCreateResponse,
        stability="stable",
        owner_module="x",
        target_kinds=("global",),
        side_effects=("db_write",),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )
    assert permission_key_for(entry) == PERM_ITEMS_WRITE
