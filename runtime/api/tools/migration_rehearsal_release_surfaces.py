"""Exercise release drivers after a migration copy has converged.

Schema and migration invariants prove stored rows. Release rehearsal also
needs to prove that the current build can consume those rows through the
same deployment-run and release-pin paths used to ship it. Every mutation
here targets the disposable copy selected by ``bound_pg_dsn``.
"""

from __future__ import annotations

from typing import Any

from yoke_cli.commands.release_pin_agreement import evaluate_pin_health_agreement
from yoke_contracts.release_pin import (
    DESIRED_PIN_PATH_KEY,
    PROBE_URL_PATH_KEY,
    RELEASE_PIN_CAPABILITY,
    SERVED_PIN_RESPONSE_PATH_KEY,
)
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_target_resolution import cmd_resolve_target
from yoke_core.domain.deployment_runs_crud_mutate import cmd_create_run
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from yoke_core.domain.release_pin_record import record_release_pin
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
    read_key_path,
)


_REHEARSAL_LINEAGE = "0" * 40
_REHEARSAL_PIN = "migration-rehearsal-pin"


def verify_migrated_release_surfaces(conn: Any, copy_dsn: str) -> str | None:
    """Return a failure detail when the migrated copy cannot drive a release."""
    try:
        _validate_capability_contracts(conn)
        with db_backend.bound_pg_dsn(copy_dsn):
            _exercise_deployment_run_drivers(conn)
            _exercise_release_pin_round_trips(conn)
    except BaseException as exc:  # noqa: BLE001 - rehearsal verdict, not crash
        detail = str(exc).strip().replace(copy_dsn, "<dsn>")
        return (
            "release tooling invariants failed -- "
            f"{type(exc).__name__}: {detail or '(no detail)'}"
        )
    return None


def _validate_capability_contracts(conn: Any) -> None:
    rows = conn.execute(
        "SELECT project_id,type,COALESCE(settings, '{}') AS settings "
        "FROM project_capabilities ORDER BY project_id,type"
    ).fetchall()
    for row in rows:
        project_id = int(_cell(row, "project_id", 0))
        cap_type = str(_cell(row, "type", 1))
        settings = str(_cell(row, "settings", 2) or "{}")
        try:
            canonicalize_capability_settings(cap_type, settings)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"project {project_id} capability {cap_type!r} violates the "
                f"shipped settings contract: {exc}"
            ) from exc


def _exercise_deployment_run_drivers(conn: Any) -> None:
    rows = conn.execute(
        "SELECT p.slug AS project,df.id AS flow "
        "FROM deployment_flows df JOIN projects p ON p.id=df.project_id "
        "WHERE df.status='active' ORDER BY p.slug,df.id"
    ).fetchall()
    for row in rows:
        project = str(_cell(row, "project", 0))
        flow = str(_cell(row, "flow", 1))
        tier, environment_id, _environment = cmd_resolve_target(project, flow)
        run_id = cmd_create_run(
            project,
            flow,
            release_lineage=_REHEARSAL_LINEAGE,
            created_by="migration-rehearsal",
        )
        created = conn.execute(
            "SELECT target_tier,target_environment_id FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if created is None:
            raise AssertionError(f"deployment run create returned absent {run_id!r}")
        created_tier = str(_cell(created, "target_tier", 0) or "")
        created_environment = _cell(created, "target_environment_id", 1)
        if created_tier != tier or created_environment != environment_id:
            raise AssertionError(
                f"deployment flow {flow!r} resolved to {(tier, environment_id)!r} "
                f"but create stored {(created_tier, created_environment)!r}"
            )


def _exercise_release_pin_round_trips(conn: Any) -> None:
    capabilities = conn.execute(
        "SELECT p.slug AS project,pc.project_id,pc.settings "
        "FROM project_capabilities pc JOIN projects p ON p.id=pc.project_id "
        "WHERE pc.type=%s ORDER BY p.slug",
        (RELEASE_PIN_CAPABILITY,),
    ).fetchall()
    for capability in capabilities:
        project = str(_cell(capability, "project", 0))
        project_id = int(_cell(capability, "project_id", 1))
        settings = parse_settings_object(
            str(_cell(capability, "settings", 2) or "{}"),
            what=f"stored release-pin settings for {project!r}",
        )
        environments = conn.execute(
            "SELECT id,name FROM environments WHERE project_id=%s ORDER BY name",
            (project_id,),
        ).fetchall()
        for environment in environments:
            environment_id = int(_cell(environment, "id", 0))
            environment_name = str(_cell(environment, "name", 1))
            receipt = record_release_pin(project, environment_name, _REHEARSAL_PIN)
            desired_path = str(settings[DESIRED_PIN_PATH_KEY])
            if receipt.settings_path != desired_path or receipt.pin != _REHEARSAL_PIN:
                raise AssertionError(
                    f"release-pin record returned an inconsistent receipt for "
                    f"{project!r}/{environment_name!r}"
                )
            document = _environment_settings(conn, environment_id)
            desired_pin = read_key_path(document, desired_path)
            if desired_pin != _REHEARSAL_PIN:
                raise AssertionError(
                    f"release-pin record did not persist {desired_path!r} for "
                    f"{project!r}/{environment_name!r}"
                )
            _verify_release_pin(settings, document, desired_pin)


def _verify_release_pin(
    settings: dict[str, Any], document: dict[str, Any], desired_pin: Any
) -> None:
    probe_path = settings.get(PROBE_URL_PATH_KEY)
    served_path = settings.get(SERVED_PIN_RESPONSE_PATH_KEY)
    if probe_path is None and served_path is None:
        return
    probe_url = read_key_path(document, str(probe_path))
    response = apply_key_path_assignments({}, {str(served_path): desired_pin})
    agreement = evaluate_pin_health_agreement(
        desired_pin=str(desired_pin or "") or None,
        probe_url=str(probe_url or "") or None,
        desired_path=str(settings[DESIRED_PIN_PATH_KEY]),
        probe_url_path=str(probe_path),
        served_pin_response_path=str(served_path),
        opener=lambda _url: response,
    )
    if not agreement.agreed:
        raise AssertionError(agreement.error or "release-pin verification disagreed")


def _environment_settings(conn: Any, environment_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') AS settings FROM environments WHERE id=%s",
        (environment_id,),
    ).fetchone()
    if row is None:
        raise AssertionError(
            f"environment {environment_id} disappeared during rehearsal"
        )
    return parse_settings_object(
        str(_cell(row, "settings", 0) or "{}"),
        what=f"stored settings for environment {environment_id}",
    )


def _cell(row: Any, name: str, index: int) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


__all__ = ["verify_migrated_release_surfaces"]
