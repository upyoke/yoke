"""Tests for the ``strategy.ingest.run`` handler.

Covers the typed refusals (payload shape, headers), the dry-run
preview, the CAS write-back happy path (returned ``file_text`` carries
the advanced header, event carries ``source=ingest``), the conflict
outcome (teaching + per-doc payload + no ``file_text`` for the
conflicted doc), the registration shape, and the permission-key
mapping mirroring ``strategy.doc.replace``. File I/O is the caller's
(12942): payloads ship file texts read via ``read_ingest_files`` and
the tests write returned texts back the way the CLI does.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain import strategy_docs_ingest as ing
from yoke_core.domain.handlers import strategy_docs as doc_handlers
from yoke_core.domain.handlers import strategy_docs_ingest as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    SEED_CONTENT,
    SEED_SLUGS,
    SEED_UPDATED_AT,
    SESSION_WITHOUT_CLAIM,
    build_request,
    edit_rendered_body,
    ingest_files_payload,
    ok_emit,
    seed_docs,
)
from yoke_core.domain.strategy_docs_header import parse_file_text
from yoke_core.domain.strategy_docs_paths import strategy_view_path
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


class TestRefusals:
    def test_missing_files_invalid_payload(self, tmp_db: str) -> None:
        outcome = handlers.handle_ingest(_ingest_request({}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "files" in outcome.error.message

    def test_empty_files_list_invalid_payload(self, tmp_db: str) -> None:
        outcome = handlers.handle_ingest(_ingest_request({"files": []}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_headerless_file_typed_code(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        strategy_view_path(checkout, "PAD").write_text(
            "# PAD\n\nheaderless\n", encoding="utf-8",
        )
        outcome = handlers.handle_ingest(
            _ingest_request(ingest_files_payload(checkout, ["PAD"]))
        )
        assert outcome.error.code == "ingest_header_invalid"
        assert "PAD.md" in outcome.error.message

    def test_missing_file_raises_client_side(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        # The file read happens in the CLI before dispatch; the typed
        # message names the path and teaches the render recovery.
        strategy_view_path(checkout, "PAD").unlink()
        with pytest.raises(ing.StrategyIngestFileMissingError) as exc:
            ing.read_ingest_files(checkout, ["PAD"])
        assert "PAD.md" in str(exc.value)


class TestDryRun:
    def test_previews_without_writing(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_rendered_body(checkout, "PAD", SEED_CONTENT["PAD"] + "More.\n")
        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_ingest(
                _ingest_request(
                    ingest_files_payload(checkout, list(SEED_SLUGS), dry_run=True)
                )
            )
        assert outcome.primary_success is True
        payload = outcome.result_payload
        statuses = {d["slug"]: d["status"] for d in payload["docs"]}
        assert statuses["PAD"] == "changed"
        assert payload["written"] == 0
        assert payload["unchanged"] == len(SEED_SLUGS) - 1
        emit.assert_not_called()
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


class TestWriteBack:
    def test_written_doc_rerenders_and_emits_source_ingest(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        new_body = SEED_CONTENT["VISION"] + "Sharper vision.\n"
        edit_rendered_body(checkout, "VISION", new_body)
        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_ingest(
                _ingest_request(ingest_files_payload(checkout, ["VISION"]))
            )
        assert outcome.primary_success is True
        (doc,) = outcome.result_payload["docs"]
        assert doc["status"] == "written"

        # The returned file_text carries the advanced header: writing it
        # (as the CLI does) makes a re-run no-op.
        parsed = parse_file_text(doc["file_text"])
        assert parsed.updated_at == doc["updated_at"]
        assert parsed.body == new_body

        emit.assert_called_once()
        context = emit.call_args.kwargs["context"]
        assert context["slug"] == "VISION"
        assert context["source"] == "ingest"

    def test_rerun_after_write_noops(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edit_rendered_body(checkout, "VISION", SEED_CONTENT["VISION"] + "More.\n")
        from yoke_core.domain.strategy_docs_render import (
            write_rendered_files,
        )

        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ):
            first = handlers.handle_ingest(
                _ingest_request(ingest_files_payload(checkout, ["VISION"]))
            )
            # The CLI writes the returned file_text back; re-reading the
            # advanced file makes the second run a no-op.
            write_rendered_files(checkout, first.result_payload["docs"])
            again = handlers.handle_ingest(
                _ingest_request(ingest_files_payload(checkout, ["VISION"]))
            )
        assert again.primary_success is True
        assert again.result_payload["docs"][0]["status"] == "unchanged"


class TestConflict:
    def _bump_row(self, tmp_db: str, slug: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} "
                "SET content = %s, updated_at = %s "
                "WHERE project_id = %s AND slug = %s",
                (
                    SEED_CONTENT[slug] + "\nDB moved on.\n",
                    "2026-06-11T11:11:11Z",
                    PROJECT_ID,
                    slug,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_conflict_outcome_teaches_and_preserves_edit(
        self, tmp_db: str, checkout: Path,
    ) -> None:
        edited_body = SEED_CONTENT["PAD"] + "Local edit.\n"
        edit_rendered_body(checkout, "PAD", edited_body)
        before = strategy_view_path(checkout, "PAD").read_text(encoding="utf-8")
        self._bump_row(tmp_db, "PAD")
        with patch.object(
            doc_handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_ingest(
                _ingest_request(ingest_files_payload(checkout, ["PAD"]))
            )
        assert outcome.primary_success is False
        assert outcome.error.code == "ingest_conflict"
        assert "yoke strategy render" in outcome.error.message
        assert "git diff" in outcome.error.message
        assert outcome.result_payload["conflicts"] == 1
        conflicted = outcome.result_payload["docs"][0]
        assert conflicted["status"] == "conflict"
        # No file_text for a conflicted doc — the edited file holds the
        # operator's only copy of their edits and must not be rewritten.
        assert "file_text" not in conflicted
        emit.assert_not_called()
        after = strategy_view_path(checkout, "PAD").read_text(encoding="utf-8")
        assert after == before


def test_registration_shape() -> None:
    (entry,) = handlers.REGISTRATIONS
    assert entry["function_id"] == "strategy.ingest.run"
    assert entry["owner_module"] == (
        "yoke_core.domain.handlers.strategy_docs_ingest"
    )
    assert entry["target_kinds"] == ["global"]
    assert entry["side_effects"] == ["db_write", "event_emit"]
    assert "client_side_file_io" in entry["guardrails"]
    assert entry["emitted_event_names"] == [
        handlers.STRATEGY_DOC_REPLACED_EVENT_NAME
    ]
    assert "compare_and_swap_base" in entry["guardrails"]
    assert "foreign_process_claim_refused" in entry["guardrails"]
    assert entry["ambient_session_required"] is False


def test_permission_key_mirrors_replace() -> None:
    from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
    from yoke_core.domain.yoke_function_permissions import (
        permission_key_for,
    )
    from yoke_core.domain.yoke_function_registry import RegistryEntry

    def _entry(function_id: str, side_effects: tuple) -> RegistryEntry:
        return RegistryEntry(
            function_id=function_id,
            handler=lambda r: None,
            request_model=handlers.IngestRequest,
            response_model=handlers.IngestResponse,
            stability="stable",
            owner_module="x",
            target_kinds=("global",),
            side_effects=side_effects,
            emitted_event_names=(),
            guardrails=(),
            adapter_status="live",
        )

    ingest_key = permission_key_for(
        _entry("strategy.ingest.run", ("db_write",))
    )
    replace_key = permission_key_for(
        _entry("strategy.doc.replace", ("db_write",))
    )
    assert ingest_key == replace_key == PERM_ITEMS_WRITE
