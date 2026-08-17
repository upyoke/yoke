"""Tests for ``projects.environment.update``."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import projects_restart
from yoke_core.domain.handlers import projects_infrastructure_create as create
from yoke_core.domain.handlers import projects_infrastructure_update as update
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

WEBAPP = "externalwebapp"
SITE = "externalwebapp-web"
ENVIRONMENT = "externalwebapp-web-production"


@pytest.fixture
def infrastructure_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        projects_restart.cmd_init()
        yield db_path


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _seed_named_environment() -> None:
    create.handle_projects_site_create(
        _request("projects.site.create", {
            "project": WEBAPP, "site_slug": SITE,
        })
    )
    create.handle_projects_environment_create(
        _request("projects.environment.create", {
            "project": WEBAPP,
            "site_slug": SITE,
            "environment_id": ENVIRONMENT,
        })
    )


def test_renames_environment_and_keeps_id(infrastructure_db) -> None:
    _seed_named_environment()
    outcome = update.handle_projects_environment_update(
        _request("projects.environment.update", {
            "project": WEBAPP,
            "environment_id": ENVIRONMENT,
            "name": "prod",
        })
    )
    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "project": WEBAPP,
        "environment_id": ENVIRONMENT,
        "name": "prod",
        "previous_name": "production",
    }
    conn = connect_test_db(infrastructure_db)
    try:
        row = conn.execute(
            "SELECT id, name FROM environments WHERE id = %s",
            (ENVIRONMENT,),
        ).fetchone()
    finally:
        conn.close()
    assert (str(row[0]), str(row[1])) == (ENVIRONMENT, "prod")


def test_refuses_name_outside_delivery_set(infrastructure_db) -> None:
    _seed_named_environment()
    outcome = update.handle_projects_environment_update(
        _request("projects.environment.update", {
            "project": WEBAPP,
            "environment_id": ENVIRONMENT,
            "name": "production",
        })
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_registration_spec_covers_update() -> None:
    ids = [spec["function_id"] for spec in update.REGISTRATION_SPECS]
    assert ids == ["projects.environment.update"]
