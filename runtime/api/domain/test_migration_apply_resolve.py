"""Regression coverage for ``_resolve_capability_settings``.

Pins the canonical-resolution contract: ``project_capabilities`` is
always read from the canonical Yoke control-plane DB regardless of
the connection passed in; canonical-DB unreachability surfaces as a
typed :class:`MigrationApplyError`, not a raw backend exception.
"""

from __future__ import annotations

import pytest
from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_apply_resolve import (
    _resolve_capability_settings,
)
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _connect_validation_db,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


class TestCanonicalResolution:
    def test_resolves_capability_when_passed_validation_surface_conn(
        self, apply_env
    ) -> None:
        validation_conn = _connect_validation_db(apply_env)
        try:
            with pytest.raises(db_backend.operational_error_types(conn=validation_conn)):
                validation_conn.execute(
                    "SELECT 1 FROM project_capabilities LIMIT 1"
                )
            capability = _resolve_capability_settings(
                validation_conn, "yoke"
            )
        finally:
            validation_conn.close()
        assert capability["models"]["primary"]["runner"]["kind"] == (
            "governed_migration_module"
        )

    def test_resolves_capability_when_passed_canonical_conn(
        self, apply_env
    ) -> None:
        canonical_conn = _conn(apply_env["control_db"])
        try:
            capability = _resolve_capability_settings(
                canonical_conn, "yoke"
            )
        finally:
            canonical_conn.close()
        assert capability["models"]["primary"]["runner"]["kind"] == (
            "governed_migration_module"
        )

    def test_ignores_conn_argument_entirely(
        self, apply_env
    ) -> None:
        """Passing a closed connection still succeeds — the canonical
        resolver does the lookup independent of *conn*."""
        closed_conn = _connect_validation_db(apply_env)
        closed_conn.close()
        capability = _resolve_capability_settings(closed_conn, "yoke")
        assert "models" in capability


class TestTypedErrors:
    def test_unknown_project_raises_typed_error(self, apply_env) -> None:
        dummy_conn = _connect_validation_db(apply_env)
        try:
            with pytest.raises(MigrationApplyError) as exc:
                _resolve_capability_settings(dummy_conn, "no-such-project")
        finally:
            dummy_conn.close()
        assert "no-such-project" in str(exc.value)
        assert "no migration_model capability row" in str(exc.value)

    def test_empty_settings_raises_typed_error(
        self, apply_env, monkeypatch
    ) -> None:
        canonical_conn = _conn(apply_env["control_db"])
        try:
            canonical_conn.execute(
                "UPDATE project_capabilities SET settings = '{}' "
                "WHERE project_id = %s AND type = %s",
                (1, "migration_model"),
            )
            canonical_conn.commit()
        finally:
            canonical_conn.close()
        dummy_conn = _connect_validation_db(apply_env)
        try:
            with pytest.raises(MigrationApplyError) as exc:
                _resolve_capability_settings(dummy_conn, "yoke")
        finally:
            dummy_conn.close()
        assert "empty or malformed" in str(exc.value)
