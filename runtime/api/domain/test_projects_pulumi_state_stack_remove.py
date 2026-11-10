"""Removal of one stack's Pulumi operator state after `pulumi stack rm`."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    PulumiCheckpointImportError,
)
from yoke_core.domain.projects_pulumi_state_stack_remove import remove_stack_state


_ENTRY = {"secrets_provider": "awskms://alias/yoke-pulumi", "encrypted_key": "secret-ciphertext"}


@pytest.fixture
def stack_state_db():
    with pg_testdb.test_database() as database:
        db_name = database.info.dbname
        conn = pg_testdb.connect_test_database(db_name)
        try:
            project_id = resolve_project_id(conn, "yoke")
            settings = {
                "state_bucket": "bucket",
                "stack_state": {"yoke-drill-vps": _ENTRY, "yoke-keep": _ENTRY},
            }
            conn.execute(
                "INSERT INTO project_capabilities (created_at, project_id, type, settings) VALUES ('2026-01-01T00:00:00Z', %s, %s, %s)",
                (project_id, "pulumi-state", json.dumps(settings)),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_name


def _settings(db_name: str) -> dict:
    conn = pg_testdb.connect_test_database(db_name)
    try:
        raw = conn.execute(
            "SELECT settings FROM project_capabilities WHERE type='pulumi-state'"
        ).fetchone()[0]
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    finally:
        conn.close()


def test_remove_drops_only_the_named_stack_and_repeats_cleanly(stack_state_db):
    receipt = remove_stack_state(project="yoke", stack_name="yoke-drill-vps")
    assert receipt["mode"] == "removed"
    assert receipt["changed_paths"] == [
        "project_capabilities.settings.stack_state.yoke-drill-vps"
    ]
    assert "ciphertext" not in json.dumps(receipt)
    settings = _settings(stack_state_db)
    assert settings["stack_state"] == {"yoke-keep": _ENTRY}
    assert settings["state_bucket"] == "bucket"

    repeated = remove_stack_state(project="yoke", stack_name="yoke-drill-vps")
    assert repeated["mode"] == "not_registered"
    assert repeated["changed_paths"] == []


def test_remove_refuses_unknown_project_and_blank_stack(stack_state_db):
    with pytest.raises(PulumiCheckpointImportError) as missing:
        remove_stack_state(project="no-such-project", stack_name="yoke-drill-vps")
    assert missing.value.code == "not_found"
    with pytest.raises(PulumiCheckpointImportError) as blank:
        remove_stack_state(project="yoke", stack_name=" ")
    assert blank.value.code == "validation_error"
    assert "yoke-drill-vps" in _settings(stack_state_db)["stack_state"]
