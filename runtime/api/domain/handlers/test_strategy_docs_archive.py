"""Tests for ``strategy.doc.archive`` / ``strategy.doc.unarchive`` and the
archived-state surfaces they drive (``set_doc_archived``, ``get_doc`` /
``list_docs`` archived fields, and the bundle-render unification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs_archive as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    SESSION_WITH_CLAIM,
    SESSION_WITHOUT_CLAIM,
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


def _request(function: str, slug: str, session_id: str = SESSION_WITHOUT_CLAIM):
    return build_request(function, {"slug": slug}, session_id=session_id, actor_id="7")


def _archived_at(db_path: str, slug: str):
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            f"SELECT archived_at FROM {sd.STRATEGY_DOCS_TABLE} "
            "WHERE project_id = %s AND slug = %s",
            (PROJECT_ID, slug),
        ).fetchone()
        return row["archived_at"]
    finally:
        conn.close()


class TestArchiveHandler:
    def test_archive_then_unarchive_round_trip(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        with patch.object(handlers._events, "emit_event", return_value=ok_emit()) as emit:
            out = handlers.handle_doc_archive(_request("strategy.doc.archive", "PAD"))
        assert out.primary_success is True
        assert out.result_payload["archived"] is True
        assert out.result_payload["changed"] is True
        assert out.result_payload["archived_at"] is not None
        assert _archived_at(tmp_db, "PAD") is not None
        assert emit.call_count == 1
        assert emit.call_args.args[0] == handlers.STRATEGY_DOC_ARCHIVED_EVENT_NAME

        with patch.object(handlers._events, "emit_event", return_value=ok_emit()) as emit:
            out = handlers.handle_doc_unarchive(_request("strategy.doc.unarchive", "PAD"))
        assert out.result_payload["archived"] is False
        assert out.result_payload["changed"] is True
        assert _archived_at(tmp_db, "PAD") is None
        assert emit.call_args.args[0] == handlers.STRATEGY_DOC_UNARCHIVED_EVENT_NAME

    def test_archiving_already_archived_is_idempotent_noop(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()

        with patch.object(handlers._events, "emit_event", return_value=ok_emit()):
            handlers.handle_doc_archive(_request("strategy.doc.archive", "PAD"))
        with patch.object(handlers._events, "emit_event", return_value=ok_emit()) as emit:
            out = handlers.handle_doc_archive(_request("strategy.doc.archive", "PAD"))
        # A no-op flip advances nothing and emits no event.
        assert out.result_payload["changed"] is False
        assert out.result_payload["archived"] is True
        assert emit.call_count == 0

    def test_archive_does_not_require_own_process_claim(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()
        # No claim held by this session — archive is allowed (mirrors doc.create).
        with patch.object(handlers._events, "emit_event", return_value=ok_emit()):
            out = handlers.handle_doc_archive(_request("strategy.doc.archive", "PAD"))
        assert out.primary_success is True

    def test_archive_blocked_by_foreign_process_claim(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            seed_session(conn, SESSION_WITH_CLAIM)
            seed_process_claim(conn, SESSION_WITH_CLAIM)
        finally:
            conn.close()
        # A DIFFERENT session tries to archive while the foreign session holds
        # the live STRATEGIZE claim — refused.
        with patch.object(handlers._events, "emit_event", return_value=ok_emit()):
            out = handlers.handle_doc_archive(
                _request("strategy.doc.archive", "PAD", session_id=SESSION_WITHOUT_CLAIM)
            )
        assert out.primary_success is False
        assert out.error.code == "archive_blocked_by_live_process_claim"

    def test_unknown_slug_errors(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
        finally:
            conn.close()
        with patch.object(handlers._events, "emit_event", return_value=ok_emit()):
            out = handlers.handle_doc_archive(
                _request("strategy.doc.archive", "NOPE-NOT-SEEDED")
            )
        assert out.primary_success is False
        assert out.error.code == "doc_not_seeded"

    def test_registration_shape(self) -> None:
        ids = {r["function_id"] for r in handlers.REGISTRATIONS}
        assert ids == {"strategy.doc.archive", "strategy.doc.unarchive"}
        for reg in handlers.REGISTRATIONS:
            assert "event_emit" in reg["side_effects"]
            assert reg["emitted_event_names"]


class TestArchivedStateSurfaces:
    def test_set_doc_archived_and_get_doc_surface_archived_at(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            assert sd.get_doc(conn, PROJECT_ID, "PAD")["archived_at"] is None
            res = sd.set_doc_archived(conn, PROJECT_ID, "PAD", archived=True)
            assert res["changed"] is True and res["archived"] is True
            assert sd.get_doc(conn, PROJECT_ID, "PAD")["archived_at"] is not None
            # list_docs marks the archived doc.
            by_slug = {d["slug"]: d for d in sd.list_docs(conn, PROJECT_ID)}
            assert by_slug["PAD"]["archived"] is True
            assert by_slug["MISSION"]["archived"] is False
        finally:
            conn.close()


class TestBundleRenderUnification:
    def test_bundle_matches_render_including_updated_by_and_archive_path(
        self, tmp_db: str,
    ) -> None:
        from yoke_core.domain.project_install_strategy import bundle_strategy_files
        from yoke_core.domain.strategy_docs_render import render_file_map
        from yoke_contracts.project_contract.strategy_docs_paths import (
            strategy_view_rel_path,
        )

        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn)
            # Set a non-null updated_by on one row — the old install-side render
            # dropped this header field, so bundle bytes diverged from render.
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} SET updated_by_actor_id = 7 "
                "WHERE project_id = %s AND slug = %s",
                (PROJECT_ID, "VISION"),
            )
            conn.commit()
            sd.set_doc_archived(conn, PROJECT_ID, "PAD", archived=True)

            bundle = {e["path"]: e["content"] for e in bundle_strategy_files(conn, PROJECT_ID, "yoke")}
            rendered = render_file_map(conn, PROJECT_ID)
        finally:
            conn.close()

        # The unification invariant: the install bundle's bytes for every doc
        # (including the updated_by-set VISION row that the old install-side
        # render used to drop) are byte-identical to `yoke strategy render`,
        # because both now go through the one shared render_file_map.
        assert len(bundle) == len(rendered)
        for entry in rendered:
            rel = strategy_view_rel_path(entry["slug"], entry["archived"])
            assert bundle[rel] == entry["file_text"], entry["slug"]
        # The archived doc routed under archive/, the active ones did not.
        assert ".yoke/strategy/archive/PAD.md" in bundle
        assert ".yoke/strategy/VISION.md" in bundle
