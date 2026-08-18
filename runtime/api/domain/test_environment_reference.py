"""Environments are addressed by their registered name within a project."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import environment_reference


def _seed(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS projects ("
        "id BIGINT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sites ("
        "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), "
        "name TEXT NOT NULL, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS environments ("
        "id TEXT PRIMARY KEY, site TEXT NOT NULL REFERENCES sites(id), "
        "name TEXT NOT NULL, created_at TEXT, UNIQUE(site, name))"
    )
    conn.execute("INSERT INTO projects (id, slug) VALUES (41, 'yoke')")
    conn.execute("INSERT INTO projects (id, slug) VALUES (43, 'platform')")
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES ('yoke', 41, 'Yoke', 'now'), ('yoke-api', 43, 'Yoke API', 'now')"
    )
    # Two projects each registering an environment named 'prod' is the normal
    # case the resolver must keep apart.
    conn.execute(
        "INSERT INTO environments (id, site, name, created_at) VALUES "
        "('production', 'yoke', 'prod', 'now'), "
        "('stage', 'yoke', 'stage', 'now'), "
        "('yoke-api-prod', 'yoke-api', 'prod', 'now')"
    )
    conn.commit()


def _connect(tmp_path: Path):
    from runtime.api.fixtures.file_test_db import init_test_db
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            _seed(conn)
        finally:
            conn.close()

    return init_test_db(tmp_path, apply_schema=_apply), db_backend


def test_name_resolves_within_its_own_project(tmp_path: Path) -> None:
    context, db_backend = _connect(tmp_path)
    with context:
        conn = db_backend.connect()
        try:
            yoke_prod = environment_reference.resolve(conn, project_id=41, name="prod")
            platform_prod = environment_reference.resolve(conn, project_id=43, name="prod")
        finally:
            conn.close()

    assert yoke_prod.name == platform_prod.name == "prod"
    assert yoke_prod.id != platform_prod.id
    assert yoke_prod.project_id == 41
    assert platform_prod.project_id == 43


def test_an_unregistered_name_refuses_and_names_what_is_registered(
    tmp_path: Path,
) -> None:
    context, db_backend = _connect(tmp_path)
    with context:
        conn = db_backend.connect()
        try:
            with pytest.raises(environment_reference.EnvironmentReferenceError) as caught:
                environment_reference.resolve(conn, project_id=41, name="production")
            message = str(caught.value)
            registered = environment_reference.registered_names(conn, project_id=41)
        finally:
            conn.close()

    # The retired spelling is exactly the mistake this refusal has to explain.
    assert "'production' is not registered" in message
    assert "prod" in message and "stage" in message
    assert registered == ["prod", "stage"]


def test_an_empty_name_refuses_rather_than_selecting_a_default(
    tmp_path: Path,
) -> None:
    context, db_backend = _connect(tmp_path)
    with context:
        conn = db_backend.connect()
        try:
            with pytest.raises(environment_reference.EnvironmentReferenceError):
                environment_reference.resolve(conn, project_id=41, name="   ")
        finally:
            conn.close()
