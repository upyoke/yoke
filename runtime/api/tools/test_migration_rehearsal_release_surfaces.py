# ruff: noqa: F811
"""Release-surface invariants exercised on migrated rehearsal copies."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_api_release_pin_record_route import (
    release_pin_db,  # noqa: F401 -- imported fixture
)
from runtime.api.tools import migration_rehearsal_release_surfaces as surfaces
from runtime.api.tools.yoke_migration_fleet import rehearsal_plan
from yoke_core.domain import db_backend


class _Cursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, handler: Any) -> None:
        self.handler = handler

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        return _Cursor(self.handler(sql, params))


def test_yoke_rehearsal_plan_binds_release_surface_validation() -> None:
    assert (
        rehearsal_plan().post_converge_validator
        is surfaces.verify_migrated_release_surfaces
    )


def test_release_surfaces_run_against_disposable_postgres(release_pin_db: dict) -> None:
    with connect_test_db(release_pin_db["db_path"]) as conn:
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id,project_id,name,stages,created_at,target_tier,"
            "target_environment_id,status) VALUES "
            "('rehearsal-release',1,'Rehearsal release','[]',"
            "'2026-01-01T00:00:00Z','persistent',201,'active')"
        )
        conn.commit()
        detail = surfaces.verify_migrated_release_surfaces(
            conn,
            db_backend.resolve_pg_dsn(),
        )
        created = conn.execute(
            "SELECT target_environment_id FROM deployment_runs "
            "WHERE flow='rehearsal-release' AND created_by='migration-rehearsal'"
        ).fetchone()

    assert detail is None
    assert created is not None and created[0] == 201


def test_legacy_release_pin_document_fails_the_shipped_contract() -> None:
    conn = _Connection(
        lambda sql, _params: (
            [
                {
                    "project_id": 1,
                    "type": "release_pin",
                    "settings": json.dumps(
                        {
                            "pin_file": "VERSION",
                            "branch_by_environment": {"stage": "main"},
                        }
                    ),
                }
            ]
            if "FROM project_capabilities ORDER BY" in sql
            else []
        )
    )

    detail = surfaces.verify_migrated_release_surfaces(conn, "password=secret")

    assert detail is not None
    assert "shipped settings contract" in detail
    assert "pin_file" in detail
    assert "secret" not in detail


def test_deployment_run_resolve_and_create_must_agree(monkeypatch: Any) -> None:
    created: dict[str, tuple[str, int]] = {}
    calls: list[tuple[str, str]] = []

    def handler(sql: str, params: tuple[Any, ...]) -> list[Any]:
        if "FROM deployment_flows df" in sql:
            return [{"project": "yoke", "flow": "release-stage"}]
        if "FROM deployment_runs" in sql:
            tier, environment_id = created[str(params[0])]
            return [{"target_tier": tier, "target_environment_id": environment_id}]
        raise AssertionError(sql)

    def resolve(project: str, flow: str) -> tuple[str, int, str]:
        calls.append((project, flow))
        return "persistent", 7, "stage"

    def create(project: str, flow: str, **_kwargs: Any) -> str:
        calls.append((project, flow))
        created["run-1"] = ("persistent", 7)
        return "run-1"

    monkeypatch.setattr(surfaces, "cmd_resolve_target", resolve)
    monkeypatch.setattr(surfaces, "cmd_create_run", create)

    surfaces._exercise_deployment_run_drivers(_Connection(handler))

    assert calls == [("yoke", "release-stage"), ("yoke", "release-stage")]


def test_release_pin_record_and_verify_round_trip(monkeypatch: Any) -> None:
    capability = {
        "desired_pin_path": "delivery.pin",
        "probe_url_path": "monitoring.url",
        "served_pin_response_path": "build.pin",
    }
    environment = {
        "delivery": {"pin": "old"},
        "monitoring": {"url": "https://example.invalid/health"},
    }

    def handler(sql: str, _params: tuple[Any, ...]) -> list[Any]:
        if "FROM project_capabilities pc" in sql:
            return [
                {
                    "project": "yoke",
                    "project_id": 1,
                    "settings": json.dumps(capability),
                }
            ]
        if "SELECT id,name FROM environments" in sql:
            return [{"id": 9, "name": "stage"}]
        if "SELECT COALESCE(settings" in sql:
            return [{"settings": json.dumps(environment)}]
        raise AssertionError(sql)

    def record(project: str, environment_name: str, pin: str) -> Any:
        assert (project, environment_name) == ("yoke", "stage")
        environment["delivery"]["pin"] = pin
        return SimpleNamespace(settings_path="delivery.pin", pin=pin)

    monkeypatch.setattr(surfaces, "record_release_pin", record)

    surfaces._exercise_release_pin_round_trips(_Connection(handler))

    assert environment["delivery"]["pin"] == "migration-rehearsal-pin"


def test_driver_target_disagreement_fails_closed(monkeypatch: Any) -> None:
    def handler(sql: str, _params: tuple[Any, ...]) -> list[Any]:
        if "FROM deployment_flows df" in sql:
            return [{"project": "yoke", "flow": "release-stage"}]
        return [{"target_tier": "persistent", "target_environment_id": 8}]

    monkeypatch.setattr(
        surfaces,
        "cmd_resolve_target",
        lambda *_args: ("persistent", 7, "stage"),
    )
    monkeypatch.setattr(surfaces, "cmd_create_run", lambda *_args, **_kwargs: "run-1")

    with pytest.raises(AssertionError, match="resolved"):
        surfaces._exercise_deployment_run_drivers(_Connection(handler))
