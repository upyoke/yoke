"""Refresh contract: omit unchanged bodies and measure transfer size."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.project_contract.strategy_docs_header import content_sha256
from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers import strategy_docs as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    PROJECT_ID,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    build_request,
    seed_docs,
)
from yoke_core.domain.json_helper import dumps_compact
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

ARCHIVE_SLUGS = ("PAD", "WISPS")
ARCHIVE_BODY = ("archived-corpus-line\n" * 80)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _seed_mixed(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_docs(conn)
        for slug in ARCHIVE_SLUGS:
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} SET content = %s "
                "WHERE project_id = %s AND slug = %s",
                (ARCHIVE_BODY, PROJECT_ID, slug),
            )
            sd.set_doc_archived(conn, PROJECT_ID, slug, archived=True)
        conn.commit()
    finally:
        conn.close()


def _result_bytes(payload: dict) -> int:
    return len(dumps_compact(payload).encode("utf-8"))


def _wire_bytes(payload: dict) -> int:
    envelope = FunctionCallResponse(
        success=True,
        function="strategy.render.run",
        version="v1",
        request_id="refresh-size",
        result=payload,
    )
    return len(envelope.model_dump_json().encode("utf-8"))


def _render(payload: dict) -> dict:
    outcome = handlers.handle_render(
        build_request("strategy.render.run", payload)
    )
    assert outcome.primary_success is True
    return outcome.result_payload


class TestRenderRefreshTransfer:
    def test_empty_payload_skips_archives(self, tmp_db: str) -> None:
        _seed_mixed(tmp_db)
        payload = _render({})
        slugs = {doc["slug"] for doc in payload["docs"]}
        assert slugs.isdisjoint(ARCHIVE_SLUGS)
        assert all("file_text" in doc for doc in payload["docs"])

    def test_include_archives_sends_archived_bodies(self, tmp_db: str) -> None:
        _seed_mixed(tmp_db)
        payload = _render({"include_archives": True})
        slugs = {doc["slug"] for doc in payload["docs"]}
        assert set(ARCHIVE_SLUGS) <= slugs

    def test_unchanged_and_single_change_shrink_result_and_wire(
        self, tmp_db: str,
    ) -> None:
        _seed_mixed(tmp_db)
        first = _render({})
        first_result = _result_bytes(first)
        first_wire = _wire_bytes(first)
        known = [
            {
                "slug": doc["slug"],
                "updated_at": doc["updated_at"],
                "content_sha256": doc["content_sha256"],
                "archived": doc["archived"],
            }
            for doc in first["docs"]
        ]
        unchanged = _render({"known": known})
        for doc in unchanged["docs"]:
            assert doc["unchanged"] is True
            assert "file_text" not in doc
        unchanged_result = _result_bytes(unchanged)
        unchanged_wire = _wire_bytes(unchanged)
        assert unchanged_result < first_result
        assert unchanged_wire < first_wire

        conn = connect_test_db(tmp_db)
        try:
            sd.replace_doc(
                conn, PROJECT_ID, "MISSION",
                SEED_CONTENT["MISSION"] + "changed.\n",
                None, base_updated_at=SEED_UPDATED_AT,
            )
        finally:
            conn.close()
        mixed = _render({"known": known})
        by_slug = {doc["slug"]: doc for doc in mixed["docs"]}
        assert "file_text" in by_slug["MISSION"]
        assert by_slug["MISSION"]["unchanged"] is False
        assert by_slug["VISION"]["unchanged"] is True
        assert "file_text" not in by_slug["VISION"]
        mixed_result = _result_bytes(mixed)
        mixed_wire = _wire_bytes(mixed)
        assert unchanged_result < mixed_result < first_result
        assert unchanged_wire < mixed_wire < first_wire

    def test_known_hash_is_of_db_body(self, tmp_db: str) -> None:
        _seed_mixed(tmp_db)
        payload = _render({"slugs": ["MISSION"]})
        (doc,) = payload["docs"]
        assert doc["content_sha256"] == content_sha256(SEED_CONTENT["MISSION"])
