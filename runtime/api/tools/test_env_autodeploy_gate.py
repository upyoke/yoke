"""Tests for the env_autodeploy_gate CLI against disposable Postgres.

Exercises the full CLI path — policy resolution through
``load_project_renderer_settings`` plus the deployment_flows prod-refusal
lookup — on a minimal project/site/environment/flow fixture schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.tools import env_autodeploy_gate as gate


def _apply_schema() -> None:
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, "
            "slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
            "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE sites (id TEXT PRIMARY KEY, "
            "project_id INTEGER NOT NULL, name TEXT NOT NULL, "
            "settings TEXT DEFAULT '{}', created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE environments (id TEXT PRIMARY KEY, "
            "site TEXT NOT NULL, name TEXT NOT NULL, "
            "settings TEXT DEFAULT '{}', created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE deployment_flows (id TEXT PRIMARY KEY, "
            "project_id INTEGER NOT NULL, target_env TEXT, "
            "created_at TEXT NOT NULL)"
        )
        now = iso8601_now()
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            "VALUES (1, 'yoke', 'Yoke', %s)",
            (now,),
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) "
            "VALUES ('yoke-api', 1, 'Yoke API', %s)",
            (now,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def gate_db(tmp_path: Path) -> Iterator[str]:
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        yield db_path


def _add_env(env_id: str, name: str, settings: dict) -> None:
    conn = db_backend.connect()
    try:
        conn.execute(
            "INSERT INTO environments (id, site, name, settings, created_at) "
            "VALUES (%s, 'yoke-api', %s, %s, %s)",
            (env_id, name, json.dumps(settings), iso8601_now()),
        )
        conn.commit()
    finally:
        conn.close()


def _add_flow(flow_id: str, target_env: Optional[str]) -> None:
    conn = db_backend.connect()
    try:
        conn.execute(
            "INSERT INTO deployment_flows (id, project_id, target_env, "
            "created_at) VALUES (%s, 1, %s, %s)",
            (flow_id, target_env, iso8601_now()),
        )
        conn.commit()
    finally:
        conn.close()


def _stage_settings(auto_on_push: bool = True) -> dict:
    settings: dict = {"git": {"branch": "stage"}}
    if auto_on_push:
        settings["deploy"] = {"auto_on_push": True}
    return settings


class TestEnvAutodeployGate:
    def test_opted_in_env_prints_name_and_exits_zero(self, gate_db, capsys):
        _add_env("yoke-api-stage", "stage", _stage_settings())
        _add_flow("yoke-stage-release", "stage")
        assert gate.main(["yoke", "stage"]) == gate.EXIT_MATCH
        assert capsys.readouterr().out == "stage\n"

    def test_no_policy_exits_three_with_clean_no_op_line(self, gate_db, capsys):
        _add_env("yoke-api-stage", "stage", _stage_settings(auto_on_push=False))
        assert gate.main(["yoke", "stage"]) == gate.EXIT_NO_MATCH
        assert "no env auto-deploys from this branch" in capsys.readouterr().out

    def test_wrong_branch_exits_three(self, gate_db, capsys):
        _add_env("yoke-api-stage", "stage", _stage_settings())
        assert gate.main(["yoke", "main"]) == gate.EXIT_NO_MATCH
        assert "no env auto-deploys from this branch" in capsys.readouterr().out

    @pytest.mark.parametrize("env_name", ["prod", "production"])
    def test_prod_named_env_refused_regardless_of_policy(
        self, gate_db, capsys, env_name
    ):
        _add_env(
            f"yoke-api-{env_name}",
            env_name,
            {"git": {"branch": "main"}, "deploy": {"auto_on_push": True}},
        )
        assert gate.main(["yoke", "main"]) == gate.EXIT_PROD_REFUSED
        err = capsys.readouterr().err
        assert "structurally excluded" in err
        assert env_name in err

    def test_prod_release_flow_target_refused_despite_neutral_name(
        self, gate_db, capsys
    ):
        # Defense-in-depth: an env not named prod/production is still
        # refused when it is the target of the prod release flow.
        _add_env(
            "yoke-api-live",
            "live",
            {"git": {"branch": "main"}, "deploy": {"auto_on_push": True}},
        )
        _add_flow("yoke-prod-release", "live")
        assert gate.main(["yoke", "main"]) == gate.EXIT_PROD_REFUSED
        err = capsys.readouterr().err
        assert "yoke-prod-release" in err
        assert "structurally excluded" in err
