# ruff: noqa: F811
"""Release-surface invariants exercised on migrated rehearsal copies."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    two_project_release,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_api_release_pin_record_route import (
    release_pin_db,  # noqa: F401 -- imported fixture
)
from runtime.api.tools import migration_rehearsal_release_surfaces as surfaces
from yoke_core.domain.deployment_runs_crud_mutate import CompositionRefused
from yoke_core.domain.deployment_run_ci_tested_source import ReleaseSourceRefused
from yoke_core.domain.project_github_auth_models import MissingAppCredentials
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


@pytest.mark.parametrize(
    "refusal",
    [
        CompositionRefused("composition cannot resolve synthetic lineage"),
        ReleaseSourceRefused("release_source_unverifiable", "copied auth unavailable"),
        MissingAppCredentials("example", "service issuer is not mounted"),
    ],
)
def test_domain_verdict_counts_as_a_driver_answer(monkeypatch: Any, refusal) -> None:
    def handler(sql: str, _params: tuple[Any, ...]) -> list[Any]:
        if "FROM deployment_flows df" in sql:
            return [{"project": "yoke", "flow": "release-stage"}]
        raise AssertionError(f"refused create must not be read back: {sql}")

    def refuse(*_args: Any, **_kwargs: Any) -> str:
        raise refusal

    monkeypatch.setattr(
        surfaces,
        "cmd_resolve_target",
        lambda *_args: ("persistent", 7, "stage"),
    )
    monkeypatch.setattr(surfaces, "cmd_create_run", refuse)

    surfaces._exercise_deployment_run_drivers(_Connection(handler))


def test_broken_run_driver_still_fails_the_rehearsal(monkeypatch: Any) -> None:
    def handler(sql: str, _params: tuple[Any, ...]) -> list[Any]:
        if "FROM project_capabilities ORDER BY" in sql:
            return []
        if "FROM deployment_flows df" in sql:
            return [{"project": "yoke", "flow": "release-stage"}]
        raise AssertionError(sql)

    def crash(*_args: Any, **_kwargs: Any) -> str:
        raise LookupError("deployment_runs.composition_resolution is missing")

    monkeypatch.setattr(
        surfaces,
        "cmd_resolve_target",
        lambda *_args: ("persistent", 7, "stage"),
    )
    monkeypatch.setattr(surfaces, "cmd_create_run", crash)

    detail = surfaces.verify_migrated_release_surfaces(
        _Connection(handler), "password=secret"
    )

    assert detail is not None
    assert "LookupError" in detail
    assert "composition_resolution is missing" in detail


def test_custody_flow_with_a_prior_release_does_not_fail_the_rehearsal(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape that broke a prod preflight: custody flow, prior release.

    Carried-work derivation compares the run's lineage against the preceding
    succeeded run's. The rehearsal lineage names no real commit, so a flow
    that takes delivery custody and has already shipped once cannot resolve
    it and composition refuses. The migrated rows were read and judged, which
    is what the rehearsal asked, so the verdict must not fail it.
    """
    two_project_release(test_db, tmp_path, monkeypatch)
    environment = test_db.execute(
        "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_flows SET status='active',target_tier='persistent',"
        "target_environment_id=%s WHERE id=%s",
        (environment, CARRIER_FLOW),
    )
    # The preceding run is only this run's predecessor when it shipped to the
    # same environment, so without this the rehearsal run would be a baseline
    # rather than the comparison this test is about.
    test_db.execute(
        "UPDATE deployment_runs SET target_tier='persistent',"
        "target_environment_id=%s WHERE id='run-previous'",
        (environment,),
    )
    test_db.commit()
    before = test_db.execute("SELECT count(*) FROM deployment_runs").fetchone()[0]

    # Establish that this flow really does refuse, so the rehearsal below is
    # proving tolerance rather than passing because nothing refused.
    with pytest.raises(CompositionRefused) as refusal:
        surfaces.cmd_create_run(
            "yoke",
            CARRIER_FLOW,
            release_lineage=surfaces._REHEARSAL_LINEAGE,
            created_by="migration-rehearsal",
        )
    assert "current_release_lineage_unreachable" in str(refusal.value)

    surfaces._exercise_deployment_run_drivers(test_db)

    assert (
        test_db.execute("SELECT count(*) FROM deployment_runs").fetchone()[0] == before
    )
