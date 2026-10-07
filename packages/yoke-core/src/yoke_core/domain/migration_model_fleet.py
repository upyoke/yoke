"""Which live databases a migration model's releases must keep serving.

Rehearsing a history entry against the model's validation surface proves
nothing about the databases behind it, because that surface is current. Before
a release carries an entry, a throwaway copy of every live database the model
owns is converged through that model's real boot sequence. This module is the
declaration of what "every live database" and "its real boot sequence" mean
for one model, so the same preflight and the same release gate serve every
project.

A model declares one ``fleet`` of three kinds:

``engine_tenants``
    The engine's own tenant databases on the environment's admin cluster,
    converged by the engine's boot-time schema and history convergence.

``named_databases``
    Databases named explicitly on the environment's admin cluster. Each copy
    is converged by the project's own boot command (``converge_argv``), run
    from the project checkout with the copy's DSN bound to the model's
    ``runner.config.connection_env_var``. An optional ``verify_argv`` runs the
    same way afterwards and must exit 0. ``schema_shape_sources`` names the
    checkout files whose content is the schema that boot converges, so a
    release whose shape moved is rehearsed even when no entry was added.

``none``
    The model has no live databases a release must rehearse — for example a
    single database on a host the admin cluster cannot copy. ``reason`` says
    why, and the release gate prints it rather than rehearsing.

The fleet lives on the model in the project's ``migration_model`` capability
settings. A release gate refuses a model that declares no fleet at all: an
undeclared fleet and an empty one are different facts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

FLEET_ENGINE_TENANTS = "engine_tenants"
FLEET_NAMED_DATABASES = "named_databases"
FLEET_NONE = "none"
FLEET_KINDS = (FLEET_ENGINE_TENANTS, FLEET_NAMED_DATABASES, FLEET_NONE)

#: Registered read serving a project's migration_model declaration.
CAPABILITY_FUNCTION_ID = "projects.capability_settings.get"

_DATABASE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_fleet(value: Any, error: type) -> Dict[str, Any]:
    """Normalize one model's ``fleet`` declaration, raising *error* on refusal."""
    if not isinstance(value, dict):
        raise error(f"fleet must be a JSON object; got {type(value).__name__}")
    kind = value.get("kind")
    if kind not in FLEET_KINDS:
        raise error(f"fleet.kind {kind!r} is not one of {list(FLEET_KINDS)}")
    allowed = {
        FLEET_ENGINE_TENANTS: {"kind"},
        FLEET_NAMED_DATABASES: {
            "kind",
            "names",
            "converge_argv",
            "verify_argv",
            "schema_shape_sources",
        },
        FLEET_NONE: {"kind", "reason"},
    }[kind]
    extra = set(value) - allowed
    if extra:
        raise error(f"fleet has unknown keys for kind {kind!r}: {sorted(extra)}")
    if kind == FLEET_ENGINE_TENANTS:
        return {"kind": kind}
    if kind == FLEET_NONE:
        reason = value.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise error(
                "fleet.reason must say why this model has no live databases "
                "a release must rehearse"
            )
        return {"kind": kind, "reason": reason.strip()}
    names = _string_list(value.get("names"), field="fleet.names", error=error)
    for name in names:
        if not _DATABASE_NAME_RE.match(name):
            raise error(f"fleet.names entry {name!r} is not a database name")
    if len(set(names)) != len(names):
        raise error("fleet.names must not repeat a database")
    out: Dict[str, Any] = {
        "kind": kind,
        "names": names,
        "converge_argv": _string_list(
            value.get("converge_argv"), field="fleet.converge_argv", error=error
        ),
        "schema_shape_sources": [
            _checkout_relative(path, error=error)
            for path in _string_list(
                value.get("schema_shape_sources"),
                field="fleet.schema_shape_sources",
                error=error,
            )
        ],
    }
    if "verify_argv" in value:
        out["verify_argv"] = _string_list(
            value.get("verify_argv"), field="fleet.verify_argv", error=error
        )
    return out


def _string_list(value: Any, *, field: str, error: type) -> List[str]:
    if not isinstance(value, list) or not value:
        raise error(f"{field} must be a non-empty list of strings")
    if any(not isinstance(part, str) or not part.strip() for part in value):
        raise error(f"{field} entries must be non-empty strings")
    return [part.strip() for part in value]


def _checkout_relative(path: str, *, error: type) -> str:
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise error(
            f"fleet.schema_shape_sources entry {path!r} must be a path inside "
            "the project checkout"
        )
    return pure.as_posix()


def fleet_of(model: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The model's declared fleet, or ``None`` when it declares none at all."""
    fleet = model.get("fleet")
    return dict(fleet) if isinstance(fleet, Mapping) else None


def undeclared_refusal(project: str, model_name: str) -> str:
    """Why a release cannot proceed for a model with no fleet, and the fix."""
    return (
        f"migration model {model_name!r} of project {project!r} declares no "
        "fleet, so the release cannot say which live databases must be "
        "rehearsed. Declare one on the model with `yoke projects "
        f"capability-settings merge --project {project} --cap-type "
        f"migration_model` — `fleet.kind` is `{FLEET_ENGINE_TENANTS}`, "
        f"`{FLEET_NAMED_DATABASES}` (names, converge_argv, "
        f"schema_shape_sources), or `{FLEET_NONE}` with a reason. Contract: "
        ".yoke/docs/reference/db-reference/migration-model-fleet.md."
    )


def read_capability(project: str) -> Tuple[Dict[str, Any], str]:
    """The project's validated ``migration_model`` capability, or why not.

    ``({}, "")`` means the project declares no migration model at all.

    Read through the registered capability read, so a gate on a relayed
    control plane and a preflight beside a local one read the same document.
    An unreadable declaration fails closed: guessing it would report a release
    as carrying nothing to rehearse.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.migration_model_capability_validation import (
        MigrationModelCapabilityError,
        validate,
    )

    unknown = f"could not read the migration_model capability of project {project!r}"
    try:
        response = call_dispatcher(
            function_id=CAPABILITY_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": project, "cap_type": "migration_model"},
        )
    except Exception as exc:  # noqa: BLE001 - unreadable declaration fails closed
        return {}, f"{unknown}: {exc}"
    if not response.success:
        if response.error is not None and response.error.code == "not_found":
            # No declaration means the project governs no database migrations.
            return {}, ""
        detail = (
            response.error.message
            if response.error is not None
            else "capability read refused"
        )
        return {}, f"{unknown}: {detail}"
    result = response.result if isinstance(response.result, Mapping) else {}
    raw = str(result.get("settings_json") or "")
    try:
        return validate(json.loads(raw)), ""
    except (MigrationModelCapabilityError, TypeError, ValueError) as exc:
        return {}, f"{unknown}: {exc}"


def schema_shape_digest(fleet: Mapping[str, Any], checkout: Path) -> str:
    """Schema-shape digest of the sources this fleet's boot converges."""
    from yoke_core.domain import schema_shape_source

    if fleet["kind"] == FLEET_ENGINE_TENANTS:
        return schema_shape_source.digest_schema_shape()
    return schema_shape_source.digest_declared_sources(
        checkout, fleet["schema_shape_sources"]
    )


def schema_shape_digest_at(
    fleet: Mapping[str, Any], repository: Path, commit_sha: str
) -> str:
    """The same digest read from one exact commit of the project repository."""
    from yoke_core.domain import schema_shape_source

    if fleet["kind"] == FLEET_ENGINE_TENANTS:
        return schema_shape_source.digest_schema_shape_commit(repository, commit_sha)
    return schema_shape_source.digest_declared_sources_commit(
        repository, commit_sha, fleet["schema_shape_sources"]
    )


__all__ = [
    "CAPABILITY_FUNCTION_ID",
    "FLEET_ENGINE_TENANTS",
    "FLEET_KINDS",
    "FLEET_NAMED_DATABASES",
    "FLEET_NONE",
    "fleet_of",
    "read_capability",
    "schema_shape_digest",
    "schema_shape_digest_at",
    "undeclared_refusal",
    "validate_fleet",
]
