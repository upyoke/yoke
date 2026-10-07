"""Which live databases a migration model's releases must keep serving.

Rehearsing a history entry against the model's validation surface proves
nothing about the databases behind it, because that surface is current. Before
a release carries an entry, a throwaway copy of every live database the model
owns is converged through that model's real boot sequence. This module is the
contract for declaring what "every live database" and "its real boot
sequence" mean for one model, so one preflight and one release gate serve
every project.

Each model named in the project's ``migration_model`` capability declares one
fleet in the project's ``migration_fleet`` capability,
``{"models": {"<model>": <fleet>}}``. The fleet is release evidence
configuration, so it is its own document beside the authoring declaration
rather than a key inside it. A fleet is one of three kinds:

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

A release gate refuses a model that declares no fleet at all: an undeclared
fleet and an empty one are different facts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

FLEET_ENGINE_TENANTS = "engine_tenants"
FLEET_NAMED_DATABASES = "named_databases"
FLEET_NONE = "none"
FLEET_KINDS = (FLEET_ENGINE_TENANTS, FLEET_NAMED_DATABASES, FLEET_NONE)

#: ``project_capabilities.type`` of the per-model fleet declarations.
CAPABILITY_TYPE = "migration_fleet"

_DATABASE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class MigrationFleetError(ValueError):
    """A ``migration_fleet`` capability payload fails validation."""


def validate_capability(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a ``migration_fleet`` settings document."""
    if not isinstance(payload, dict) or set(payload) != {"models"}:
        raise MigrationFleetError(
            'migration_fleet settings must be {"models": {"<model>": <fleet>}}'
        )
    models = payload["models"]
    if not isinstance(models, dict) or not models:
        raise MigrationFleetError("migration_fleet requires a non-empty 'models' dict")
    out: Dict[str, Any] = {}
    for name in sorted(models):
        if not isinstance(name, str) or not _MODEL_NAME_RE.match(name):
            raise MigrationFleetError(f"models key {name!r} is not a model name")
        out[name] = validate_fleet(models[name])
    return {"models": out}


def validate_json_string(raw: str) -> str:
    """Parse, validate, and return compact canonical capability JSON."""
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise MigrationFleetError(f"malformed JSON: {exc}") from exc
    return json.dumps(
        validate_capability(payload), sort_keys=True, separators=(",", ":")
    )


def validate_fleet(value: Any, error: type = MigrationFleetError) -> Dict[str, Any]:
    """Normalize one model's fleet declaration, raising *error* on refusal."""
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


def undeclared_refusal(project: str, model_name: str) -> str:
    """Why a release cannot proceed for a model with no fleet, and the fix."""
    return (
        f"migration model {model_name!r} of project {project!r} declares no "
        "fleet, so the release cannot say which live databases must be "
        "rehearsed. Declare it in the project's migration_fleet capability: "
        f"`yoke projects capability-settings merge --project {project} "
        f"--cap-type {CAPABILITY_TYPE} --set models.{model_name}=<fleet JSON>` "
        "(`capability-settings set --new` creates the document). The fleet "
        f"kind is `{FLEET_ENGINE_TENANTS}`, `{FLEET_NAMED_DATABASES}` (names, "
        f"converge_argv, schema_shape_sources), or `{FLEET_NONE}` with a "
        "reason. Contract: "
        ".yoke/docs/reference/db-reference/migration-model-fleet.md."
    )


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
    "CAPABILITY_TYPE",
    "FLEET_ENGINE_TENANTS",
    "FLEET_KINDS",
    "FLEET_NAMED_DATABASES",
    "FLEET_NONE",
    "MigrationFleetError",
    "schema_shape_digest",
    "schema_shape_digest_at",
    "undeclared_refusal",
    "validate_capability",
    "validate_fleet",
    "validate_json_string",
]
