"""Tests for the strategy replace guard codes, render handler, and
registration shape.

Sibling of ``test_strategy_docs.py`` (reads + the replace claim gate);
shared seeds live in ``_strategy_docs_test_helpers.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    PROJECT_SLUG,
    SEED_CONTENT,
    SEED_SLUGS,
    SEED_UPDATED_AT,
    SESSION_WITH_CLAIM,
    build_request,
    ok_emit,
    seed_docs,
    seed_process_claim,
    seed_session,
)
from yoke_core.domain.strategy_docs_header import render_file_text
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


class TestDocReplaceGuards:
    def _claimed(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()

    def test_invalid_slug_shape_code(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "../escape", "content": "# long enough body here\n",
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert outcome.error.code == "unknown_slug"

    def test_row_missing_code(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "NOT-A-DOC", "content": "# long enough body here\n",
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert outcome.error.code == "doc_not_seeded"

    def test_empty_content_code(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "MISSION", "content": "  \n",
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert outcome.error.code == "empty_content_refused"

    def test_rendered_file_text_stores_body_only(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        new_content = SEED_CONTENT["MISSION"] + "\nRendered-file edit.\n"
        rendered_content = render_file_text(
            "MISSION", SEED_UPDATED_AT, new_content,
        )
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ):
            outcome = handlers.handle_doc_replace(
                build_request(
                    "strategy.doc.replace",
                    {"slug": "MISSION", "content": rendered_content,
                     "base_updated_at": SEED_UPDATED_AT},
                    session_id=SESSION_WITH_CLAIM,
                )
            )
        assert outcome.primary_success is True

        conn = connect_test_db(tmp_db)
        try:
            row = conn.execute(
                f"SELECT content FROM {sd.STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_ID, "MISSION"),
            ).fetchone()
        finally:
            conn.close()
        assert str(row["content"]) == new_content

    def test_rendered_file_for_other_slug_code(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        rendered_content = render_file_text(
            "VISION", SEED_UPDATED_AT, SEED_CONTENT["VISION"],
        )
        outcome = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "MISSION", "content": rendered_content,
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert outcome.error.code == "invalid_strategy_header"
        assert "VISION" in outcome.error.message
        assert "MISSION" in outcome.error.message

    def test_shrink_guard_code_and_force_bypass(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        denied = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "MISSION", "content": "# tiny\n",
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert denied.error.code == "shrink_guard_refused"

        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ):
            forced = handlers.handle_doc_replace(
                build_request(
                    "strategy.doc.replace",
                    {"slug": "MISSION", "content": "# tiny\n", "force": True,
                     "base_updated_at": SEED_UPDATED_AT},
                    session_id=SESSION_WITH_CLAIM,
                )
            )
        assert forced.primary_success is True

    def test_stale_base_conflict_code(self, tmp_db: str) -> None:
        self._claimed(tmp_db)
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ):
            first = handlers.handle_doc_replace(
                build_request(
                    "strategy.doc.replace",
                    {"slug": "MISSION",
                     "content": SEED_CONTENT["MISSION"] + "first\n",
                     "base_updated_at": SEED_UPDATED_AT},
                    session_id=SESSION_WITH_CLAIM,
                )
            )
        assert first.primary_success is True
        stale = handlers.handle_doc_replace(
            build_request(
                "strategy.doc.replace",
                {"slug": "MISSION",
                 "content": SEED_CONTENT["MISSION"] + "second\n",
                 "base_updated_at": SEED_UPDATED_AT},
                session_id=SESSION_WITH_CLAIM,
            )
        )
        assert stale.primary_success is False
        assert stale.error.code == "replace_conflict"
        assert "doc get MISSION" in stale.error.message


class TestRender:
    def test_render_unseeded_project_typed_code(self, tmp_db: str) -> None:
        outcome = handlers.handle_render(build_request("strategy.render.run", {}))
        assert outcome.primary_success is False
        assert outcome.error.code == "doc_not_seeded"
        assert "seed-defaults" in outcome.error.message

    def test_render_returns_file_texts_client_writes(
        self, tmp_db: str, tmp_path: Path,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        outcome = handlers.handle_render(
            build_request("strategy.render.run", {})
        )

        assert outcome.primary_success is True
        assert outcome.result_payload["project_id"] == PROJECT_ID
        assert outcome.result_payload["project_slug"] == PROJECT_SLUG
        docs = outcome.result_payload["docs"]
        assert sorted(d["slug"] for d in docs) == sorted(SEED_SLUGS)

        # The client half (the CLI) writes the returned texts; composed
        # here the way yoke strategy render does.
        from yoke_core.domain.strategy_docs_header import parse_file_text
        from yoke_core.domain.strategy_docs_paths import strategy_view_path
        from yoke_core.domain.strategy_docs_render import (
            write_rendered_files,
        )

        target_root = tmp_path / "checkout"
        report = write_rendered_files(target_root, docs)
        assert report == {slug: "written" for slug in SEED_SLUGS}
        parsed = parse_file_text(
            strategy_view_path(target_root, "MISSION").read_text(
                encoding="utf-8"
            )
        )
        assert parsed.slug == "MISSION"
        assert parsed.body == SEED_CONTENT["MISSION"]
        # Byte-idempotent: a second write of the same texts no-ops.
        assert write_rendered_files(target_root, docs) == {
            slug: "unchanged" for slug in SEED_SLUGS
        }

    def test_render_slug_subset(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()
        outcome = handlers.handle_render(
            build_request("strategy.render.run", {"slugs": ["MISSION"]})
        )
        assert outcome.primary_success is True
        (doc,) = outcome.result_payload["docs"]
        assert doc["slug"] == "MISSION"


def test_registrations_shape() -> None:
    by_id = {entry["function_id"]: entry for entry in handlers.REGISTRATIONS}
    assert set(by_id) == {
        "strategy.doc.list",
        "strategy.doc.get",
        "strategy.doc.replace",
        "strategy.render.run",
    }
    for entry in by_id.values():
        assert entry["stability"] == "stable"
        assert entry["target_kinds"] == ["global"]
        assert entry["adapter_status"] == "live"
        assert entry["claim_required_kind"] is None
        assert entry["owner_module"] == "yoke_core.domain.handlers.strategy_docs"
    assert by_id["strategy.doc.list"]["side_effects"] == []
    assert by_id["strategy.doc.get"]["side_effects"] == []
    assert by_id["strategy.doc.replace"]["side_effects"] == ["db_write", "event_emit"]
    assert by_id["strategy.doc.replace"]["emitted_event_names"] == [
        handlers.STRATEGY_DOC_REPLACED_EVENT_NAME
    ]
    assert by_id["strategy.render.run"]["side_effects"] == []
    assert "client_side_file_io" in by_id["strategy.render.run"]["guardrails"]
