"""Read a project's own declared database for a db-admin profile.

A project declares where each governed database lives in its
``migration_model`` capability: ``models.<MODEL>.authoritative_db`` with
``kind="postgres"`` and a ``location`` naming the database and the Pulumi
outputs that carry its endpoint and managed-secret ARN. A db-admin profile for
that database reads the declaration through a named HTTPS control plane and
pairs it with the deploy environment's stack, bastion, and region, so each
environment reaches its own copy of the declared database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.db_admin_control_plane import _relay_control_plane_read
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError, _safe_label

MIGRATION_MODEL_CAPABILITY = "migration_model"
DECLARATION_DOC = "docs/public/reference/db-reference/migration-model-capabilities.md"


@dataclass(frozen=True)
class DeclaredDatabase:
    """Non-secret facts locating one project-declared Postgres database."""

    model: str
    database_name: str
    endpoint_output: str
    secret_arn_output: str

    def as_report(self) -> dict[str, str]:
        return {
            "model": self.model,
            "database_name": self.database_name,
            "endpoint_output": self.endpoint_output,
            "secret_arn_output": self.secret_arn_output,
        }


def declared_admin_env_name(project: str, env_name: str, model: str) -> str:
    """Default profile name: ``<project>-<env>-<model>-db-admin``."""
    return (
        f"{_safe_label(project, what='project')}-"
        f"{_safe_label(env_name, what='environment')}-"
        f"{_safe_label(model, what='database model')}"
        f"{contract.DB_ADMIN_ENV_SUFFIX}"
    )


def read_declared_database(
    project: str,
    model: str,
    *,
    control_plane_env: str,
    config_path: str | Path | None,
) -> DeclaredDatabase:
    """Read ``models.<model>.authoritative_db`` from the project declaration."""
    model = _safe_label(model, what="database model")
    teach = (
        f"declare it as settings.models.{model}.authoritative_db "
        f"(kind postgres, location with database_name, endpoint_output, "
        f"secret_arn_output) on project {project!r}'s {MIGRATION_MODEL_CAPABILITY} "
        f"capability; see {DECLARATION_DOC}"
    )
    result = _relay_control_plane_read(
        control_plane_env,
        function_id="projects.capability_settings.get",
        payload={"project": project, "cap_type": MIGRATION_MODEL_CAPABILITY},
        config_path=config_path,
        what=f"{MIGRATION_MODEL_CAPABILITY} declaration read",
        not_found=(
            f"no declared database location: project {project!r} has no "
            f"{MIGRATION_MODEL_CAPABILITY} capability; {teach}"
        ),
    )
    try:
        settings = json.loads(str(result.get("settings_json") or "{}"))
    except ValueError as exc:
        raise DbAdminSetupError(
            f"project {project!r} {MIGRATION_MODEL_CAPABILITY} settings are not JSON"
        ) from exc
    models = settings.get("models") if isinstance(settings, Mapping) else None
    declared = models.get(model) if isinstance(models, Mapping) else None
    if not isinstance(declared, Mapping):
        available = ", ".join(sorted(models)) if isinstance(models, Mapping) else ""
        raise DbAdminSetupError(
            f"no declared database location: project {project!r} declares no "
            f"database model {model!r} (declared: {available or 'none'}); "
            f"pass --database with a declared model, or {teach}"
        )
    return _postgres_location(project, model, declared.get("authoritative_db"), teach)


def _postgres_location(
    project: str,
    model: str,
    authoritative_db: Any,
    teach: str,
) -> DeclaredDatabase:
    if not isinstance(authoritative_db, Mapping):
        raise DbAdminSetupError(
            f"no declared database location: model {model!r} of project "
            f"{project!r} has no authoritative_db; {teach}"
        )
    kind = str(authoritative_db.get("kind") or "")
    if kind != "postgres":
        raise DbAdminSetupError(
            f"model {model!r} of project {project!r} is a {kind or 'undeclared'} "
            "database; db-admin profiles reach only kind postgres"
        )
    location = authoritative_db.get("location")
    location = location if isinstance(location, Mapping) else {}
    fields = ("database_name", "endpoint_output", "secret_arn_output")
    missing = [key for key in fields if not str(location.get(key) or "").strip()]
    if missing:
        raise DbAdminSetupError(
            f"no declared database location: model {model!r} of project "
            f"{project!r} is missing location keys {missing}; {teach}"
        )
    return DeclaredDatabase(
        model=model,
        database_name=str(location["database_name"]).strip(),
        endpoint_output=str(location["endpoint_output"]).strip(),
        secret_arn_output=str(location["secret_arn_output"]).strip(),
    )


__all__ = [
    "DECLARATION_DOC",
    "DeclaredDatabase",
    "MIGRATION_MODEL_CAPABILITY",
    "declared_admin_env_name",
    "read_declared_database",
]
