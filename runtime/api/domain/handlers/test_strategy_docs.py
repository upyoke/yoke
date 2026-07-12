"""Tests for the ``strategy.doc.*`` read handlers + the replace claim gate.

Covers list/get happy paths and the handler-internal process-claim
gate on ``strategy.doc.replace``: denied without an active
``strategy-control-plane:yoke`` process work-claim (typed code
``strategy_claim_required`` teaching the acquire recipe); allowed with
one (STRATEGIZE or FEED both satisfy the shared conflict group), with
the ``StrategyDocReplaced`` emission. Replace guard error codes,
render, and the registration shape live in
``test_strategy_docs_guards_render.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    OTHER_PROJECT_SLUG,
    PROJECT_ID,
    PROJECT_SLUG,
    SEED_CONTENT,
    SEED_SLUGS,
    SEED_UPDATED_AT,
    SESSION_WITHOUT_CLAIM,
    SESSION_WITH_CLAIM,
    build_request,
    ok_emit,
    seed_docs,
    seed_process_claim,
    seed_session,
)
from yoke_core.domain.work_processes import PROCESS_STRATEGIZE
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestDocList:
    def test_list_happy_path(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_doc_list(build_request("strategy.doc.list", {}))

        assert outcome.primary_success is True
        docs = outcome.result_payload["docs"]
        assert [d["slug"] for d in docs] == [
            "MISSION",
            "VISION",
            "MASTER-PLAN",
            "LANDSCAPE",
            "PAD",
            "WISPS",
        ]
        assert outcome.result_payload["project_id"] == PROJECT_ID
        assert outcome.result_payload["project_slug"] == PROJECT_SLUG
        assert [d["title"] for d in docs] == list(SEED_SLUGS)
        assert all(d["bytes"] > 0 for d in docs)

    def test_list_rejects_non_global_target(self, tmp_db: str) -> None:
        outcome = handlers.handle_doc_list(
            build_request("strategy.doc.list", {}, target_kind="item")
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_list_rejects_unexpected_payload_keys(self, tmp_db: str) -> None:
        outcome = handlers.handle_doc_list(
            build_request("strategy.doc.list", {"slug": "MISSION"})
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


class TestDocGet:
    def test_get_happy_path(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_doc_get(
            build_request("strategy.doc.get", {"slug": "MISSION"})
        )

        assert outcome.primary_success is True
        assert outcome.result_payload["slug"] == "MISSION"
        assert outcome.result_payload["content"] == SEED_CONTENT["MISSION"]

    def test_get_invalid_slug_shape(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_doc_get(
            build_request("strategy.doc.get", {"slug": "../escape"})
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "unknown_slug"

    def test_get_row_missing_teaches_corpus(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_doc_get(
            build_request("strategy.doc.get", {"slug": "NOT-A-DOC"})
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "doc_not_seeded"

    def test_get_scopes_to_target_project(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)  # project 1 corpus only
        finally:
            conn.close()

        outcome = handlers.handle_doc_get(
            build_request(
                "strategy.doc.get",
                {"slug": "MISSION"},
                project=OTHER_PROJECT_SLUG,
            )
        )

        # Project 2 has no corpus — project 1's MISSION must not leak.
        assert outcome.primary_success is False
        assert outcome.error.code == "doc_not_seeded"
        assert "seed-defaults" in outcome.error.message

    def test_project_context_required_without_any_context(
        self,
        tmp_db: str,
    ) -> None:
        outcome = handlers.handle_doc_get(
            build_request(
                "strategy.doc.get",
                {"slug": "MISSION"},
                project=None,
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "project_context_required"
        assert "--project" in outcome.error.message

    def test_unknown_project_typed_error(self, tmp_db: str) -> None:
        outcome = handlers.handle_doc_get(
            build_request(
                "strategy.doc.get",
                {"slug": "MISSION"},
                project="no-such-project",
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "project_not_found"


class TestDocReplaceClaimGate:
    def test_replace_denied_without_process_claim(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITHOUT_CLAIM)
        finally:
            conn.close()

        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {
                    "slug": "MISSION",
                    "content": SEED_CONTENT["MISSION"] + "x\n",
                    "base_updated_at": SEED_UPDATED_AT,
                },
                session_id=SESSION_WITHOUT_CLAIM,
            )
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "strategy_claim_required"
        assert handlers.CLAIM_ACQUIRE_RECIPE in outcome.error.message

    def test_replace_denied_when_claim_released(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM, released=True)
        finally:
            conn.close()

        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {
                    "slug": "MISSION",
                    "content": SEED_CONTENT["MISSION"] + "x\n",
                    "base_updated_at": SEED_UPDATED_AT,
                },
                session_id=SESSION_WITH_CLAIM,
            )
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "strategy_claim_required"

    def test_replace_denied_for_other_sessions_claim(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_session(conn, SESSION_WITHOUT_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()

        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {
                    "slug": "MISSION",
                    "content": SEED_CONTENT["MISSION"] + "x\n",
                    "base_updated_at": SEED_UPDATED_AT,
                },
                session_id=SESSION_WITHOUT_CLAIM,
            )
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "strategy_claim_required"

    def test_replace_denied_with_other_projects_claim(
        self,
        tmp_db: str,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(
                conn,
                SESSION_WITH_CLAIM,
                project_slug=OTHER_PROJECT_SLUG,
            )
        finally:
            conn.close()

        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {
                    "slug": "MISSION",
                    "content": SEED_CONTENT["MISSION"] + "x\n",
                    "base_updated_at": SEED_UPDATED_AT,
                },
                session_id=SESSION_WITH_CLAIM,
            )
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "strategy_claim_required"

    @pytest.mark.parametrize("process_key", [PROCESS_STRATEGIZE, "FEED"])
    def test_replace_allowed_with_active_claim(
        self,
        tmp_db: str,
        process_key: str,
    ) -> None:
        """STRATEGIZE or FEED both satisfy the shared conflict group."""
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM, process_key=process_key)
        finally:
            conn.close()

        new_content = SEED_CONTENT["MISSION"] + "\nNew paragraph.\n"
        with patch.object(
            handlers._events,
            "emit_event",
            return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_doc_replace(
                build_request(
                    "strategy.doc.replace",
                    {
                        "slug": "MISSION",
                        "content": new_content,
                        "base_updated_at": SEED_UPDATED_AT,
                    },
                    session_id=SESSION_WITH_CLAIM,
                    actor_id="7",
                )
            )

        assert outcome.primary_success is True
        assert outcome.result_payload["slug"] == "MISSION"
        assert outcome.result_payload["new_bytes"] == len(new_content.encode("utf-8"))
        emit.assert_called_once()
        name = emit.call_args.args[0]
        context = emit.call_args.kwargs["context"]
        assert name == handlers.STRATEGY_DOC_REPLACED_EVENT_NAME
        assert context["slug"] == "MISSION"
        assert context["old_bytes"] == len(SEED_CONTENT["MISSION"].encode("utf-8"))
        assert context["new_bytes"] == len(new_content.encode("utf-8"))
        assert context["source"] == "replace"

        conn = connect_test_db(tmp_db)
        try:
            row = conn.execute(
                f"SELECT content, updated_by_actor_id FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_ID, "MISSION"),
            ).fetchone()
        finally:
            conn.close()
        assert str(row["content"]) == new_content
        assert int(row["updated_by_actor_id"]) == 7
