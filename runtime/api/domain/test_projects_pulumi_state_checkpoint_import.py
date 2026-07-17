"""Checkpoint-derived Pulumi operator-state registration tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    PulumiCheckpointImportError,
    import_checkpoint_state,
)


@pytest.fixture
def checkpoint_state_db(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            project_id = resolve_project_id(conn, "yoke")
            conn.execute(
                "INSERT INTO project_capabilities "
                "(project_id, type, settings) VALUES (%s, %s, %s)",
                (project_id, "pulumi-state", '{"state_bucket":"bucket"}'),
            )
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def _settings(db_name: str) -> dict:
    conn = pg_testdb.connect_test_database(db_name)
    try:
        raw = conn.execute(
            "SELECT settings FROM project_capabilities "
            "WHERE type='pulumi-state'"
        ).fetchone()[0]
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    finally:
        conn.close()


def _import(*, apply: bool = False, encrypted_key: str = "ciphertext") -> dict:
    return import_checkpoint_state(
        project="yoke",
        stack_name="yoke-platform-stage-vps",
        secrets_provider="awskms://alias/yoke-pulumi",
        encrypted_key=encrypted_key,
        apply=apply,
    )


def test_checkpoint_import_dry_run_apply_and_repeat(checkpoint_state_db):
    preview = _import()
    assert preview["mode"] == "register"
    assert preview["applied"] is False
    assert preview["destination_verified"] is False
    assert "ciphertext" not in json.dumps(preview)
    assert "stack_state" not in _settings(checkpoint_state_db)

    applied = _import(apply=True)
    assert applied["mode"] == "register"
    assert applied["destination_verified"] is True
    assert _settings(checkpoint_state_db)["stack_state"] == {
        "yoke-platform-stage-vps": {
            "secrets_provider": "awskms://alias/yoke-pulumi",
            "encrypted_key": "ciphertext",
        }
    }

    repeated = _import(apply=True)
    assert repeated["mode"] == "already_registered"
    assert repeated["changed_paths"] == []
    assert len(repeated["receipt_digest"]) == 64


def test_checkpoint_import_refuses_conflict_without_write(checkpoint_state_db):
    _import(apply=True)
    with pytest.raises(PulumiCheckpointImportError) as raised:
        _import(apply=True, encrypted_key="different-ciphertext")
    assert raised.value.code == "stack_state_conflict"
    assert "different-ciphertext" not in str(raised.value)
    assert (
        _settings(checkpoint_state_db)["stack_state"]
        ["yoke-platform-stage-vps"]["encrypted_key"]
        == "ciphertext"
    )


def test_checkpoint_import_requires_awskms_and_existing_capability(
    checkpoint_state_db,
):
    with pytest.raises(PulumiCheckpointImportError) as provider:
        import_checkpoint_state(
            project="yoke",
            stack_name="yoke-platform-stage-vps",
            secrets_provider="passphrase",
            encrypted_key="ciphertext",
        )
    assert provider.value.code == "validation_error"

    conn = pg_testdb.connect_test_database(checkpoint_state_db)
    try:
        conn.execute("DELETE FROM project_capabilities WHERE type='pulumi-state'")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PulumiCheckpointImportError) as missing:
        _import(apply=True)
    assert missing.value.code == "not_found"
