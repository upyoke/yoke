"""Create-time target_env validation and last_deployed_at stamping."""

from __future__ import annotations

from runtime.api.deployment_runs_test_db import db_path  # noqa: F401
from runtime.api.fixtures.file_test_db import apply_inline_ddl, connect_test_db
import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.environment_delivery_record import UnregisteredTargetEnv
from yoke_core.domain.handlers import projects_infrastructure_create as create
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

_SITES_ENVS_DDL = """
    CREATE TABLE IF NOT EXISTS sites (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL,
        settings TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS environments (
        id TEXT PRIMARY KEY,
        site TEXT NOT NULL REFERENCES sites(id),
        name TEXT NOT NULL,
        url TEXT,
        deploy_method TEXT,
        deploy_command TEXT,
        health_check_url TEXT,
        config_notes TEXT,
        last_deployed_at TEXT,
        created_at TEXT NOT NULL,
        settings TEXT DEFAULT '{}',
        UNIQUE(site, name)
    );
"""


@pytest.fixture
def delivery_db(db_path: str):
    apply_inline_ddl(_SITES_ENVS_DDL)
    yield db_path


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _register_yoke_prod() -> None:
    assert create.handle_projects_site_create(
        _request("projects.site.create", {
            "project": "yoke", "site_slug": "yoke",
        })
    ).primary_success
    assert create.handle_projects_environment_create(
        _request("projects.environment.create", {
            "project": "yoke",
            "site_slug": "yoke",
            "environment_id": "production",
            "name": "prod",
        })
    ).primary_success


def test_create_run_refuses_unregistered_target_env(delivery_db) -> None:
    _register_yoke_prod()
    with pytest.raises(UnregisteredTargetEnv, match="registered:"):
        dr.cmd_create_run(
            "yoke", "flow-main", target_env="sandbox", db_path=delivery_db,
        )


def test_create_run_accepts_registered_name_and_id(delivery_db) -> None:
    _register_yoke_prod()
    named = dr.cmd_create_run(
        "yoke", "flow-main", target_env="prod", db_path=delivery_db,
    )
    keyed = dr.cmd_create_run(
        "yoke", "flow-main", target_env="production", db_path=delivery_db,
    )
    assert named.startswith("run-")
    assert keyed.startswith("run-")


def test_succeeded_run_stamps_last_deployed_at(delivery_db) -> None:
    _register_yoke_prod()
    run_id = dr.cmd_create_run(
        "yoke", "flow-main", target_env="prod", db_path=delivery_db,
    )
    assert dr.cmd_update(run_id, "status", "succeeded", db_path=delivery_db) is None
    conn = connect_test_db(delivery_db)
    try:
        stamped = conn.execute(
            "SELECT last_deployed_at FROM environments WHERE id = %s",
            ("production",),
        ).fetchone()
    finally:
        conn.close()
    assert stamped is not None
    assert stamped[0]


def test_empty_target_env_stays_unconstrained(delivery_db) -> None:
    _register_yoke_prod()
    run_id = dr.cmd_create_run("yoke", "flow-preview", db_path=delivery_db)
    assert run_id.startswith("run-")


def test_project_without_env_rows_stays_unconstrained(delivery_db) -> None:
    run_id = dr.cmd_create_run(
        "yoke", "flow-main", target_env="sandbox", db_path=delivery_db,
    )
    assert run_id.startswith("run-")


def test_create_run_accepts_historical_flow_target_env(delivery_db) -> None:
    assert create.handle_projects_site_create(
        _request("projects.site.create", {
            "project": "yoke", "site_slug": "yoke",
        })
    ).primary_success
    assert create.handle_projects_environment_create(
        _request("projects.environment.create", {
            "project": "yoke",
            "site_slug": "yoke",
            "environment_id": "stage",
            "name": "stage",
        })
    ).primary_success
    run_id = dr.cmd_create_run(
        "yoke", "flow-main", target_env="production", db_path=delivery_db,
    )
    assert run_id.startswith("run-")
