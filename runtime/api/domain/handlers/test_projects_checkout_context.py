"""Tests for the ``projects.checkout_context.run`` handler.

Covers the server-side project ladder (explicit client hint on
``target.project_id`` — numeric or slug — then session inference, then
the typed ``project_context_required`` teaching), payload/target
validation, and the registration + adapter-inventory shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import projects_checkout_context as handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    OTHER_PROJECT_ID,
    OTHER_PROJECT_SLUG,
    PROJECT_ID,
    PROJECT_SLUG,
    build_request,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _request(payload: dict | None = None, **kwargs):
    return build_request(
        "projects.checkout_context.run", payload or {}, **kwargs,
    )


def _seed_session_on_item(
    conn, session_id: str, *, item_id: int, project_id: int,
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, title, "
        "created_at, updated_at) "
        "VALUES (%s, %s, %s, 'checkout-context inference seed', %s, %s)",
        (item_id, project_id, item_id, now, now),
    )
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, "
        "model, project_id, workspace, offered_at, last_heartbeat, current_item_id) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', %s, '/tmp', %s, %s, %s)",
        (session_id, project_id, now, now, str(item_id)),
    )
    conn.commit()


class TestResolutionLadder:
    def test_numeric_hint_resolves_full_identity(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request(project=str(PROJECT_ID))
        )
        assert outcome.primary_success is True
        result = outcome.result_payload
        assert result["id"] == PROJECT_ID
        assert result["slug"] == PROJECT_SLUG
        assert result["name"]
        assert result["public_item_prefix"]
        assert set(result) == set(handlers.CHECKOUT_CONTEXT_FIELDS)

    def test_slug_hint_resolves(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request(project=OTHER_PROJECT_SLUG)
        )
        assert outcome.primary_success is True
        assert outcome.result_payload["id"] == OTHER_PROJECT_ID
        assert outcome.result_payload["slug"] == OTHER_PROJECT_SLUG

    def test_session_inference_when_no_hint(self, tmp_db: str) -> None:
        conn = connect_test_db(tmp_db)
        try:
            _seed_session_on_item(
                conn, "session-on-externalwebapp-item",
                item_id=901, project_id=OTHER_PROJECT_ID,
            )
        finally:
            conn.close()
        outcome = handlers.handle_projects_checkout_context(
            _request(project=None, session_id="session-on-externalwebapp-item")
        )
        assert outcome.primary_success is True
        assert outcome.result_payload["slug"] == OTHER_PROJECT_SLUG

    def test_no_context_returns_typed_teaching(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request(project=None, session_id="session-without-row")
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "project_context_required"
        assert "--project" in outcome.error.message

    def test_unknown_project_returns_not_found(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request(project="no-such-project")
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "project_not_found"


class TestValidation:
    def test_rejects_unexpected_payload_keys(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request({"field": "slug"})
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_rejects_non_global_target(self, tmp_db: str) -> None:
        outcome = handlers.handle_projects_checkout_context(
            _request(target_kind="item")
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


class TestRegistrationShape:
    def test_function_id_registered(self) -> None:
        from yoke_core.domain import yoke_function_registry as _reg
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )

        register_all_handlers()
        entry = _reg.lookup("projects.checkout_context.run")
        assert entry is not None
        assert entry.owner_module == (
            "yoke_core.domain.handlers.projects_checkout_context"
        )
        assert list(entry.target_kinds) == ["global"]
        assert entry.claim_required_kind is None
        assert list(entry.side_effects) == []

    def test_adapter_inventory_entry_present(self) -> None:
        from yoke_core.api.service_client_structured_api_adapter_inventory import (
            adapter_index,
        )

        index = adapter_index()
        assert "projects.checkout_context.run" in index
        entry = index["projects.checkout_context.run"]
        assert "projects checkout-context" in entry.cli_invocation
        assert entry.read_shape
