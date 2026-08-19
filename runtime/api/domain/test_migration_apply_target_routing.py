"""Migration models route each Postgres authority through their own binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, migration_apply_targets
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_validation_binding import (
    binding_file,
    write_binding,
)
from yoke_contracts.migration_rehearsal_teaching import PREFLIGHT_HELP_COMMAND


def _postgres_model(connection_env_var: str) -> dict:
    return {
        "authoritative_db": {
            "kind": "postgres",
            "location": {"database_name": "external_app"},
        },
        "validation_surface": {"kind": "external_validation"},
        "runner": {"config": {"connection_env_var": connection_env_var}},
    }


def test_custom_model_binding_wins_without_ambient_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model("EXTERNAL_APP_DSN")
    declared = "dbname=external_app password=declared-secret"
    monkeypatch.setenv("EXTERNAL_APP_DSN", declared)
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "dbname=ambient password=wrong-secret")
    monkeypatch.setattr(
        db_backend,
        "resolve_pg_dsn",
        lambda: pytest.fail("custom binding resolved ambient authority"),
    )

    target = migration_apply_targets.resolve_authoritative_db_target(
        tmp_path,
        model,
    )

    assert target.target == declared
    assert target.display == "postgres:external_app"


def test_missing_custom_binding_is_redacted_and_never_uses_ambient(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model("EXTERNAL_APP_DSN")
    ambient = "dbname=ambient password=ambient-secret"
    monkeypatch.delenv("EXTERNAL_APP_DSN", raising=False)
    monkeypatch.setenv(db_backend.PG_DSN_ENV, ambient)
    monkeypatch.setattr(
        db_backend,
        "resolve_pg_dsn",
        lambda: pytest.fail("missing custom binding resolved ambient authority"),
    )

    with pytest.raises(MigrationApplyError) as excinfo:
        migration_apply_targets.resolve_authoritative_db_target(tmp_path, model)

    message = str(excinfo.value)
    assert "EXTERNAL_APP_DSN" in message
    assert db_backend.PG_DSN_ENV in message
    assert ambient not in message
    assert "ambient-secret" not in message


def test_default_binding_retains_connected_authority_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model(db_backend.PG_DSN_ENV)
    resolved = "dbname=default_app password=default-secret"
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: resolved)

    target = migration_apply_targets.resolve_authoritative_db_target(
        tmp_path,
        model,
    )

    assert target.target == resolved


def test_validation_compares_with_the_resolved_model_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model("EXTERNAL_APP_DSN")
    authority = migration_apply_targets.DbTarget(
        kind="postgres",
        target="dbname=external_app password=authority-secret",
        display="postgres:external_app",
    )
    monkeypatch.setenv("EXTERNAL_APP_DSN_VALIDATION", authority.target)

    with pytest.raises(MigrationApplyError) as excinfo:
        migration_apply_targets.resolve_validation_db_target(
            worktree_path=tmp_path,
            project="external-app",
            model_name="primary",
            model=model,
            authoritative_target=authority,
            control_db_path=None,
        )

    message = str(excinfo.value)
    assert "EXTERNAL_APP_DSN_VALIDATION" in message
    assert authority.target not in message
    assert "authority-secret" not in message

    validation = "dbname=external_app_validation password=validation-secret"
    monkeypatch.setenv("EXTERNAL_APP_DSN_VALIDATION", validation)
    target = migration_apply_targets.resolve_validation_db_target(
        worktree_path=tmp_path,
        project="external-app",
        model_name="primary",
        model=model,
        authoritative_target=authority,
        control_db_path=None,
    )
    assert target.target == validation
    assert target.display == "postgres-validation:external_app_validation"


def test_unbound_validation_names_the_binding_and_the_recipe_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model("EXTERNAL_APP_DSN")
    authority = migration_apply_targets.DbTarget(
        kind="postgres",
        target="dbname=external_app password=authority-secret",
        display="postgres:external_app",
    )
    monkeypatch.delenv("EXTERNAL_APP_DSN_VALIDATION", raising=False)

    with pytest.raises(MigrationApplyError) as excinfo:
        migration_apply_targets.resolve_validation_db_target(
            worktree_path=tmp_path,
            project="external-app",
            model_name="primary",
            model=model,
            authoritative_target=authority,
            control_db_path=None,
        )

    message = str(excinfo.value)
    assert "EXTERNAL_APP_DSN_VALIDATION" in message
    assert str(binding_file("EXTERNAL_APP_DSN_VALIDATION")) in message
    assert PREFLIGHT_HELP_COMMAND in message
    assert "authority-secret" not in message


def test_written_binding_resolves_when_nothing_is_exported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = _postgres_model("EXTERNAL_APP_DSN")
    authority = migration_apply_targets.DbTarget(
        kind="postgres",
        target="dbname=external_app password=authority-secret",
        display="postgres:external_app",
    )
    monkeypatch.delenv("EXTERNAL_APP_DSN_VALIDATION", raising=False)
    validation = "dbname=external_app_validation password=validation-secret"
    write_binding("EXTERNAL_APP_DSN_VALIDATION", validation)

    target = migration_apply_targets.resolve_validation_db_target(
        worktree_path=tmp_path,
        project="external-app",
        model_name="primary",
        model=model,
        authoritative_target=authority,
        control_db_path=None,
    )

    assert target.target == validation
    assert target.display == "postgres-validation:external_app_validation"
