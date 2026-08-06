"""Resolve one project's declared history, ledger, and database authority."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Tuple

from yoke_core.domain import db_backend, json_helper, migration_ledger_contract
from yoke_core.domain.migration_history import MigrationEntry, ordered_entries
from yoke_core.domain.migration_model_capability_validation import validate
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.project_identity import resolve_project_id


class NoMigrationModel(RuntimeError):
    """The selected project declares no governed migration model."""


class MigrationConfigurationError(RuntimeError):
    """The selected model cannot describe a history and ledger safely."""


class MigrationAuthorityUnavailable(RuntimeError):
    """This runner cannot open the selected project's declared database."""


@dataclass
class ProjectMigrationState:
    project: str
    model_name: str
    history: Tuple[MigrationEntry, ...]
    ledger: migration_ledger_contract.LedgerContract
    running_version: str | None
    artifact_version_env_var: str | None
    authority_conn: Any
    closes_authority: bool

    def close(self) -> None:
        if self.closes_authority:
            self.authority_conn.close()


def resolve_project_migration_state(
    control_conn: Any, args: Any,
) -> ProjectMigrationState:
    """Resolve only facts declared by the project selected on ``args``."""
    project = str(args.project)
    payload = _capability_payload(control_conn, project)
    try:
        settings = validate(payload)
        model_name, model = _selected_model(settings)
        ledger = migration_ledger_contract.parse(
            ((model.get("runner") or {}).get("config") or {}).get("ledger")
        )
    except Exception as exc:  # noqa: BLE001 - returned as a doctor finding
        raise MigrationConfigurationError(str(exc)) from exc

    try:
        checkout = checkout_for_project(control_conn, project)
    except Exception as exc:  # noqa: BLE001 - unavailable is a visible result
        raise MigrationAuthorityUnavailable(
            f"cannot resolve the {project!r} checkout: {exc}"
        ) from exc
    if checkout is None:
        raise MigrationAuthorityUnavailable(
            f"project {project!r} has no machine-local checkout; its declared "
            "history and database cannot be examined on this runner"
        )
    config = (model.get("runner") or {}).get("config") or {}
    directory = (Path(checkout) / str(config["modules_dir"])).resolve()
    try:
        history = ordered_entries(directory)
    except Exception as exc:  # noqa: BLE001 - malformed history is a finding
        raise MigrationConfigurationError(
            f"cannot read {project}.{model_name} history at {directory}: {exc}"
        ) from exc

    authority, closes = _connect_authority(
        control_conn=control_conn,
        checkout=Path(checkout),
        project=project,
        model=model,
    )
    version_env = str(config.get("artifact_version_env_var") or "").strip()
    running_version = os.environ.get(version_env, "").strip() if version_env else ""
    return ProjectMigrationState(
        project=project,
        model_name=model_name,
        history=history,
        ledger=ledger,
        running_version=running_version or None,
        artifact_version_env_var=version_env or None,
        authority_conn=authority,
        closes_authority=closes,
    )


def ledger_rows(state: ProjectMigrationState) -> list[tuple[str, Any, Any]]:
    contract = state.ledger
    rows = state.authority_conn.execute(
        f"SELECT {contract.entry_column}, {contract.serving_floor_column}, "
        f"{contract.digest_column} "
        f"FROM {contract.table} ORDER BY {contract.entry_column}"
    ).fetchall()
    return [(str(row[0]), row[1], row[2]) for row in rows]


def _capability_payload(conn: Any, project: str) -> dict:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        project_id = resolve_project_id(conn, project)
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            f"WHERE project_id = {marker} AND type = {marker}",
            (project_id, "migration_model"),
        ).fetchone()
    except Exception as exc:  # noqa: BLE001
        raise MigrationAuthorityUnavailable(
            f"cannot read migration_model for project {project!r}: {exc}"
        ) from exc
    if row is None:
        raise NoMigrationModel(
            f"project {project!r} declares no migration_model capability"
        )
    try:
        payload = json_helper.loads_text(row[0])
    except Exception as exc:  # noqa: BLE001 - malformed config is a finding
        raise MigrationConfigurationError(
            f"project {project!r} migration_model settings are malformed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MigrationConfigurationError(
            f"project {project!r} migration_model settings are malformed"
        )
    return payload


def _selected_model(settings: dict) -> tuple[str, dict]:
    models = settings.get("models") or {}
    selected = settings.get("default_model")
    if selected:
        return str(selected), dict(models[selected])
    if len(models) == 1:
        name, model = next(iter(models.items()))
        return str(name), dict(model)
    raise MigrationConfigurationError(
        "migration_model has multiple models and no default_model"
    )


def _connect_authority(
    *, control_conn: Any, checkout: Path, project: str, model: dict,
) -> tuple[Any, bool]:
    authority = model.get("authoritative_db") or {}
    kind = str(authority.get("kind") or "")
    if kind == "sqlite_file":
        rel = ((authority.get("location") or {}).get("path"))
        target = (checkout / str(rel)).resolve()
        if not target.is_file():
            raise MigrationAuthorityUnavailable(
                f"{project} authoritative SQLite database does not exist at {target}"
            )
        conn = sqlite3.connect(str(target))
        conn.row_factory = sqlite3.Row
        return conn, True
    if kind != "postgres":
        raise MigrationConfigurationError(
            f"authoritative database kind {kind!r} is not inspectable"
        )

    from yoke_core.engines.doctor_context import self_project_names

    self_names = {str(name) for name in self_project_names(control_conn)}
    if project in self_names and db_backend.connection_is_postgres(control_conn):
        return control_conn, False

    config = (model.get("runner") or {}).get("config") or {}
    env_name = str(config.get("connection_env_var") or "")
    dsn = os.environ.get(env_name, "").strip()
    if not dsn:
        raise MigrationAuthorityUnavailable(
            f"{project} declares Postgres authority, but {env_name or 'its connection env'} "
            "is not bound on this runner"
        )
    conn = None
    try:
        conn = db_backend.connect_psycopg(dsn)
        actual = str(conn.execute("SELECT current_database()").fetchone()[0])
    except Exception as exc:  # noqa: BLE001 - cannot tell is not a pass
        if conn is not None:
            conn.close()
        raise MigrationAuthorityUnavailable(
            f"cannot connect to the {project} database bound by {env_name}: {exc}"
        ) from exc
    expected = str((authority.get("location") or {}).get("database_name") or "")
    if expected and actual != expected:
        conn.close()
        raise MigrationAuthorityUnavailable(
            f"{env_name} resolves database {actual!r}, not the declared "
            f"{project} database {expected!r}"
        )
    return conn, True


__all__ = [
    "MigrationAuthorityUnavailable",
    "MigrationConfigurationError",
    "NoMigrationModel",
    "ProjectMigrationState",
    "ledger_rows",
    "resolve_project_migration_state",
]
