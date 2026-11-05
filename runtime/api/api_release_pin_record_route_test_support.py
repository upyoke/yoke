# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture

from runtime.api.fixtures.file_test_db import connect_test_db

from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
    grant_actor_project_role,
)

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.api_tokens import mint_token

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_merge_settings,
)


@pytest.fixture()
def release_pin_db():
    fixture = make_test_db_fixture()
    db = next(fixture)
    with connect_test_db(db["db_path"]) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY, project_id INTEGER NOT "
            "NULL, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, "
            "UNIQUE(id, project_id), UNIQUE(project_id, name))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS environments (id INTEGER PRIMARY KEY, site INTEGER NOT "
            "NULL, project_id INTEGER NOT NULL, name TEXT NOT NULL, "
            "settings TEXT DEFAULT '{}', last_deployed_at TIMESTAMPTZ, "
            "created_at TIMESTAMPTZ NOT NULL, UNIQUE(project_id, name), "
            "FOREIGN KEY(site, project_id) REFERENCES sites(id, project_id))"
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) VALUES "
            "(101, 1, 'Primary API', '2026-01-01T00:00:00Z'), "
            "(102, 2, 'External API', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO environments (id, site, project_id, name, settings, created_at) "
            "VALUES (201, 101, 1, 'stage', %s, "
            "'2026-01-01T00:00:00Z'), "
            "(202, 102, 2, 'customer-east', '{}', "
            "'2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "delivery": {"engine_version": "old"},
                        "release": {"yoke_pin": "untouched"},
                        "unrelated": True,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES (1, 'release_pin', "
            "%s, '2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "desired_pin_path": "delivery.engine_version",
                    }
                ),
            ),
        )
        conn.commit()
    try:
        yield db
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


@pytest.fixture()
def client(release_pin_db):
    with _client_for_db(release_pin_db["db_path"]) as authed:
        yield authed


def _envelope(
    *,
    project: str = "yoke",
    environment: str = "stage",
    pin: str = "0.1.1+launch.188",
) -> dict:
    return {
        "function": "release_pin.record",
        "version": "v1",
        "actor": {"actor_id": "test", "session_id": "release-pin-test"},
        "target": {"kind": "global", "project_id": project},
        "payload": {
            "project": project,
            "environment": environment,
            "pin": pin,
        },
        "preconditions": {},
        "options": {},
    }


def _stored_settings(
    db_path: str,
    environment: str = "stage",
    project_id: int = 1,
) -> dict:
    with connect_test_db(db_path) as conn:
        raw = conn.execute(
            "SELECT settings FROM environments WHERE project_id=%s AND name=%s",
            (project_id, environment),
        ).fetchone()[0]
    return json.loads(str(raw))
