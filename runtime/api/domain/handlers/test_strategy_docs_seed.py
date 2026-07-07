"""Tests for the ``strategy.seed_defaults.run`` cold-start handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.handlers import strategy_docs_seed as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    OTHER_PROJECT_ID,
    OTHER_PROJECT_SLUG,
    build_request,
    ok_emit,
    seed_docs,
)
from yoke_core.domain.strategy_docs_defaults import DEFAULT_STRATEGY_DOC_SLUGS
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _seed_request(project: "str | None" = OTHER_PROJECT_SLUG):
    return build_request("strategy.seed_defaults.run", {}, project=project)


class TestSeedDefaults:
    def test_cold_start_mints_default_rows_and_emits(self, tmp_db: str) -> None:
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            outcome = handlers.handle_seed_defaults(_seed_request())
        assert outcome.primary_success is True
        payload = outcome.result_payload
        assert payload["project_id"] == OTHER_PROJECT_ID
        assert payload["project_slug"] == OTHER_PROJECT_SLUG
        assert payload["seeded"] == list(DEFAULT_STRATEGY_DOC_SLUGS)
        assert payload["already_seeded"] is False
        emit.assert_called_once()
        assert emit.call_args.args[0] == (
            handlers.STRATEGY_DEFAULTS_SEEDED_EVENT_NAME
        )
        assert emit.call_args.kwargs["context"]["seeded"] == (
            list(DEFAULT_STRATEGY_DOC_SLUGS)
        )

    def test_rerun_is_idempotent_and_silent(self, tmp_db: str) -> None:
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ) as emit:
            handlers.handle_seed_defaults(_seed_request())
            second = handlers.handle_seed_defaults(_seed_request())
        assert second.primary_success is True
        assert second.result_payload["already_seeded"] is True
        assert second.result_payload["seeded"] == []
        assert second.result_payload["existing_rows"] == len(
            DEFAULT_STRATEGY_DOC_SLUGS
        )
        # Only the cold start emitted.
        emit.assert_called_once()

    def test_established_corpus_never_extended(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            seed_docs(conn, OTHER_PROJECT_ID)
        finally:
            conn.close()
        with patch.object(
            handlers._events, "emit_event", return_value=ok_emit(),
        ):
            outcome = handlers.handle_seed_defaults(_seed_request())
        assert outcome.primary_success is True
        assert outcome.result_payload["already_seeded"] is True

    def test_project_context_required(self, tmp_db: str) -> None:
        outcome = handlers.handle_seed_defaults(_seed_request(project=None))
        assert outcome.primary_success is False
        assert outcome.error.code == "project_context_required"

    def test_rejects_unexpected_payload_keys(self, tmp_db: str) -> None:
        outcome = handlers.handle_seed_defaults(
            build_request(
                "strategy.seed_defaults.run", {"slug": "MISSION"},
                project=OTHER_PROJECT_SLUG,
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


def test_registration_shape() -> None:
    (entry,) = handlers.REGISTRATIONS
    assert entry["function_id"] == "strategy.seed_defaults.run"
    assert entry["owner_module"] == (
        "yoke_core.domain.handlers.strategy_docs_seed"
    )
    assert entry["target_kinds"] == ["global"]
    assert entry["side_effects"] == ["db_write", "event_emit"]
    assert "cold_start_only" in entry["guardrails"]
    assert entry["ambient_session_required"] is False
