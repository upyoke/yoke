"""Tests for project-scoped public item refs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import machine_config
from yoke_core.domain.yok_n_parser import parse_item_id
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _seed_refs(conn) -> None:
    conn.execute(
        """
        CREATE TABLE projects (
            id BIGINT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL DEFAULT 'TST'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE items (
            id BIGINT PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id),
            project_sequence BIGINT NOT NULL,
            UNIQUE(project_id, project_sequence)
        )
        """
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix) "
        "VALUES (1, 'alpha', 'Alpha', 'TST'), (2, 'beta', 'Beta', 'EXT')"
    )
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence) "
        "VALUES (1001, 1, 42), (2001, 2, 42)"
    )
    conn.execute(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            current_item_id TEXT,
            recent_item_id TEXT
        )
        """
    )
    conn.commit()


@pytest.fixture
def ref_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
        conn = connect_test_db(db_path)
        try:
            _seed_refs(conn)
        finally:
            conn.close()
        yield db_path


class TestParseItemId:
    def test_public_refs_resolve_by_unique_prefix(self, ref_db: str) -> None:
        conn = connect_test_db(ref_db)
        try:
            assert parse_item_id("TST-42", conn=conn) == 1001
            assert parse_item_id("EXT-42", conn=conn) == 2001
        finally:
            conn.close()

    def test_public_ref_can_verify_project_context(self, ref_db: str) -> None:
        conn = connect_test_db(ref_db)
        try:
            assert parse_item_id("TST-42", project="alpha", conn=conn) == 1001
            assert parse_item_id("ext-42", project="beta", conn=conn) == 2001
        finally:
            conn.close()

    def test_explicit_public_prefix_selects_project_over_context(
        self, ref_db: str,
    ) -> None:
        conn = connect_test_db(ref_db)
        try:
            assert parse_item_id("EXT-42", project="alpha", conn=conn) == 2001
            assert parse_item_id("TST-42", project="beta", conn=conn) == 1001
        finally:
            conn.close()

    def test_bare_number_uses_project_context_by_default(
        self, ref_db: str,
    ) -> None:
        conn = connect_test_db(ref_db)
        try:
            assert parse_item_id("42", project="alpha", conn=conn) == 1001
            assert parse_item_id("42", project="beta", conn=conn) == 2001
        finally:
            conn.close()

    def test_bare_number_uses_project_context_when_operator_mode_enabled(
        self, ref_db: str,
    ) -> None:
        conn = connect_test_db(ref_db)
        try:
            assert parse_item_id(
                "42", project="alpha", conn=conn, allow_bare_internal=False,
            ) == 1001
            assert parse_item_id(
                "42", project="beta", conn=conn, allow_bare_internal=False,
            ) == 2001
        finally:
            conn.close()

    def test_bare_number_without_project_rejected_in_operator_mode(self) -> None:
        with pytest.raises(ValueError, match="project-local"):
            parse_item_id("123", allow_bare_internal=False)

    def test_bare_integer_string_requires_project_context_by_default(self) -> None:
        with pytest.raises(ValueError, match="project-local"):
            parse_item_id("123")

    def test_bare_integer_string_internal_id_requires_explicit_opt_in(self) -> None:
        assert parse_item_id("123", allow_bare_internal=True) == 123

    def test_python_int_is_internal_id(self) -> None:
        assert parse_item_id(123) == 123

    def test_well_formed_missing_public_ref_reports_not_found(
        self, ref_db: str,
    ) -> None:
        conn = connect_test_db(ref_db)
        try:
            with pytest.raises(ValueError, match="not found"):
                parse_item_id("TST-999", conn=conn)
            with pytest.raises(ValueError, match="not found"):
                parse_item_id("999", project="alpha", conn=conn)
        finally:
            conn.close()

    def test_duplicate_public_prefix_without_context_is_rejected(self, ref_db: str) -> None:
        conn = connect_test_db(ref_db)
        try:
            conn.execute(
                "UPDATE projects SET public_item_prefix = 'TST' WHERE slug = 'beta'"
            )
            conn.commit()
            with pytest.raises(ValueError, match="shared by projects"):
                parse_item_id("TST-42", conn=conn)
        finally:
            conn.close()

    def test_project_qualifier_is_retired(self, ref_db: str) -> None:
        conn = connect_test_db(ref_db)
        try:
            with pytest.raises(ValueError, match="retired"):
                parse_item_id("alpha/TST-42", conn=conn)
        finally:
            conn.close()

    def test_invalid_refs_raise(self, ref_db: str) -> None:
        conn = connect_test_db(ref_db)
        try:
            for raw in ("", "   ", None, "garbage", "TST-", "TST-12abc"):
                with pytest.raises(ValueError):
                    parse_item_id(raw, conn=conn)
        finally:
            conn.close()

    def test_negative_int_and_bool_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_item_id(-1)
        with pytest.raises(ValueError):
            parse_item_id(True)


class TestDispatcherItemRefResolution:
    """Server-side resolution ladder against a real ref DB (the relay
    replacement for the retired client-side parse helper)."""

    @staticmethod
    def _request(item_ref: str, project: str | None = None,
                 session_id: str = "") -> "FunctionCallRequest":
        from yoke_contracts.api.function_call import (
            ActorContext,
            FunctionCallRequest,
            TargetRef,
        )

        return FunctionCallRequest(
            function="items.get.run",
            actor=ActorContext(actor_id=None, session_id=session_id),
            target=TargetRef(
                kind="item", item_ref=item_ref, project_id=project,
            ),
        )

    def test_bare_number_uses_explicit_project_context(
        self, ref_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.yoke_function_dispatch_target import (
            resolve_target_item_ref,
        )

        monkeypatch.setattr(db_helpers, "connect", lambda: connect_test_db(ref_db))

        request = self._request("42", project="beta")
        assert resolve_target_item_ref(request) is None
        assert request.target.item_id == 2001
        # the ambient hint is cleared so permission scoping derives
        # from the resolved item's own project
        assert request.target.project_id is None

    def test_bare_number_without_context_is_typed_error(
        self, ref_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.yoke_function_dispatch_target import (
            resolve_target_item_ref,
        )

        monkeypatch.setattr(db_helpers, "connect", lambda: connect_test_db(ref_db))

        request = self._request("42", session_id="no-such-session")
        response = resolve_target_item_ref(request)
        assert response is not None and not response.success
        assert response.error is not None
        assert response.error.code == "item_ref_unresolved"
        assert "project-local" in response.error.message

    def test_bare_number_uses_session_item_project_context(
        self, ref_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.yoke_function_dispatch_target import (
            resolve_target_item_ref,
        )

        conn = connect_test_db(ref_db)
        try:
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, current_item_id, recent_item_id) "
                "VALUES ('sess-beta', '2001', NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(db_helpers, "connect", lambda: connect_test_db(ref_db))

        request = self._request("42", session_id="sess-beta")
        assert resolve_target_item_ref(request) is None
        assert request.target.item_id == 2001

    def test_explicit_prefix_overrides_session_item_project_context(
        self, ref_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.yoke_function_dispatch_target import (
            resolve_target_item_ref,
        )

        conn = connect_test_db(ref_db)
        try:
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, current_item_id, recent_item_id) "
                "VALUES ('sess-beta', '2001', NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(db_helpers, "connect", lambda: connect_test_db(ref_db))

        request = self._request("TST-42", session_id="sess-beta")
        assert resolve_target_item_ref(request) is None
        assert request.target.item_id == 1001

    def test_project_qualified_refs_are_typed_errors(
        self, ref_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.yoke_function_dispatch_target import (
            resolve_target_item_ref,
        )

        monkeypatch.setattr(db_helpers, "connect", lambda: connect_test_db(ref_db))

        response = resolve_target_item_ref(self._request("alpha/TST-42"))
        assert response is not None and not response.success
        assert response.error is not None
        assert "retired" in response.error.message


class TestClientProjectContext:
    """Client-local context inference (no DB): explicit flag ->
    YOKE_PROJECT -> machine config checkout map -> None."""

    def test_machine_config_checkout_map(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_cli.commands._helpers import (
            client_project_context,
        )
        from yoke_cli.config import checkout_context

        repo = tmp_path / "checkout"
        repo.mkdir()
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "credential_source": {"kind": "env", "name": "YOKE_TOKEN"},
                },
            },
            "projects": {
                str(repo.resolve()): {"project_id": 2, "project": "beta"},
            },
        }), encoding="utf-8")

        monkeypatch.setattr(
            checkout_context, "resolve_repo_root_from_cwd", lambda: str(repo)
        )
        monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))
        monkeypatch.delenv("YOKE_PROJECT", raising=False)
        monkeypatch.chdir(repo)

        assert client_project_context() == "2"

    def test_explicit_flag_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from yoke_cli.commands._helpers import (
            client_project_context,
        )

        monkeypatch.setenv("YOKE_PROJECT", "env-project")
        assert client_project_context("flag-project") == "flag-project"
        assert client_project_context() == "env-project"
