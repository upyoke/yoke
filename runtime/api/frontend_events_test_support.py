# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from pathlib import Path

from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb

from yoke_core.api import app_factory, frontend_events_config

from yoke_core.api.routes import frontend_events

from yoke_core.domain import db_helpers, events_writes

from yoke_core.domain.auth_schema import create_auth_tables

from yoke_core.domain.schema_events import ensure_event_schema

from yoke_core.domain.org_schema import seed_default_org

from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)

from yoke_core.domain.schema_init_tables import create_core_tables

ORIGIN = "https://workbench.example.test"


@pytest.fixture
def database(monkeypatch):
    name = pg_testdb.create_test_database()

    def connect(*args, **kwargs):
        return pg_testdb.connect_test_database(name)

    with connect() as conn:
        create_core_tables(conn)
        create_actor_identity_tables(conn)
        create_auth_tables(conn)
        seed_default_org(conn)
        ensure_event_schema(conn)
        conn.commit()
    monkeypatch.setattr(db_helpers, "connect", connect)
    monkeypatch.setattr(events_writes, "connect", connect)
    yield connect
    pg_testdb.drop_test_database(name)


@pytest.fixture
def client(database):
    return TestClient(app_factory.create_app(), base_url=ORIGIN)


def headers(client, origin=ORIGIN):
    config = client.get("/api/events/config")
    assert config.status_code == 200
    return {"Origin": origin, "X-Events-Key": config.json()["publishableKey"]}


def event():
    return {
        "event_id": str(uuid4()),
        "event_name": "PageViewed",
        "event_kind": "analytics",
        "event_type": "page_view",
        "event_time": "2026-01-01T00:00:00Z",
        "session_id": str(uuid4()),
        "source_type": "frontend",
        "service": "web",
        "project": "yoke",
        "page_url": ORIGIN + "/items?token=door-secret&utm_source=email#private",
        "referrer": "https://search.test/?token=private",
        "actor_id": 999999,
        "org_id": "forged",
        "project_id": 999999,
        "context": {"project_id": 999999, "detail": {"project_id": 999999}},
    }
