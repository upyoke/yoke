"""Validation pipeline for the migration_model project capability."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

CAPABILITY_TYPE = "migration_model"
RECIPE_WEBAPP_SQLITE_EMPTY = "webapp_sqlite_empty"
RUNNER_KIND_GOVERNED_MODULE = "governed_migration_module"
_LIVE_PAIRINGS = frozenset({
    ("sqlite_file", "worktree_local_sqlite", RUNNER_KIND_GOVERNED_MODULE),
    ("postgres", "external_validation", RUNNER_KIND_GOVERNED_MODULE),
})
_ALL_AUTHORITATIVE_DB_KINDS = frozenset({"sqlite_file", "postgres", "mysql"})
_ALL_VALIDATION_SURFACE_KINDS = frozenset({
    "worktree_local_sqlite", "staging_db", "ephemeral_container", "external_validation",
})
_ALL_RUNNER_KINDS = frozenset({
    RUNNER_KIND_GOVERNED_MODULE,
    "external_adapter",
})
_KNOWN_VALIDATION_RECIPES = frozenset({
    RECIPE_WEBAPP_SQLITE_EMPTY,
})
_MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DEFAULT_CONNECTION_ENV_VAR = "YOKE_PG_DSN"

class MigrationModelCapabilityError(ValueError):
    """Raised when a ``migration_model`` capability payload fails validation."""


def _require_dict(value: Any, *, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise MigrationModelCapabilityError(
            f"{field} must be a JSON object; got {type(value).__name__}"
        )
    return value


def _require_slug(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise MigrationModelCapabilityError(
            f"{field} must be a string; got {type(value).__name__}"
        )
    if not _MODEL_NAME_RE.match(value):
        raise MigrationModelCapabilityError(
            f"{field} '{value}' must be slug-shape (lowercase alnum, '_', '-')"
        )
    return value


def _require_kind(
    value: Any, *, field: str, vocabulary: frozenset, label: str
) -> str:
    if not isinstance(value, str):
        raise MigrationModelCapabilityError(
            f"{field} must be a string; got {type(value).__name__}"
        )
    if value not in vocabulary:
        raise MigrationModelCapabilityError(
            f"{field} '{value}' is not a recognized {label} kind; "
            f"expected one of {sorted(vocabulary)}"
        )
    return value


def _validate_authoritative_db(value: Any) -> Dict[str, Any]:
    obj = _require_dict(value, field="authoritative_db")
    extra = set(obj.keys()) - {"kind", "location"}
    if extra:
        raise MigrationModelCapabilityError(
            f"authoritative_db has unknown keys: {sorted(extra)}"
        )
    kind = _require_kind(
        obj.get("kind"),
        field="authoritative_db.kind",
        vocabulary=_ALL_AUTHORITATIVE_DB_KINDS,
        label="authoritative_db",
    )
    location = obj.get("location")
    if kind == "sqlite_file":
        loc = _require_dict(location, field="authoritative_db.location")
        extra_loc = set(loc.keys()) - {"path"}
        if extra_loc:
            raise MigrationModelCapabilityError(
                f"authoritative_db.location has unknown keys for sqlite_file: {sorted(extra_loc)}"
            )
        path = loc.get("path")
        if not isinstance(path, str) or not path:
            raise MigrationModelCapabilityError(
                "authoritative_db.location.path must be a non-empty string"
            )
        return {"kind": kind, "location": {"path": path}}
    if kind == "postgres":
        loc = _require_dict(location, field="authoritative_db.location")
        allowed = {
            "stack",
            "state_backend",
            "region",
            "database_name",
            "endpoint_output",
            "secret_arn_output",
        }
        extra_loc = set(loc.keys()) - allowed
        if extra_loc:
            raise MigrationModelCapabilityError(
                "authoritative_db.location has unknown keys for postgres: "
                f"{sorted(extra_loc)}"
            )
        required = {
            "stack",
            "database_name",
            "endpoint_output",
            "secret_arn_output",
        }
        missing = [
            key for key in sorted(required)
            if not isinstance(loc.get(key), str) or not loc.get(key)
        ]
        if missing:
            raise MigrationModelCapabilityError(
                "authoritative_db.location missing required postgres keys: "
                f"{missing}"
            )
        out = {
            "stack": loc["stack"],
            "database_name": loc["database_name"],
            "endpoint_output": loc["endpoint_output"],
            "secret_arn_output": loc["secret_arn_output"],
        }
        for optional in ("state_backend", "region"):
            value = loc.get(optional)
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise MigrationModelCapabilityError(
                        f"authoritative_db.location.{optional} must be a "
                        "non-empty string when present"
                    )
                out[optional] = value
        return {"kind": kind, "location": out}
    # Non-live kinds are schema-reserved.
    raise MigrationModelCapabilityError(
        f"authoritative_db.kind '{kind}' is recognized but the combination "
        f"is not yet supported in this slice"
    )


def _validate_validation_surface(value: Any) -> Dict[str, Any]:
    obj = _require_dict(value, field="validation_surface")
    extra = set(obj.keys()) - {"kind", "provisioning"}
    if extra:
        raise MigrationModelCapabilityError(
            f"validation_surface has unknown keys: {sorted(extra)}"
        )
    kind = _require_kind(
        obj.get("kind"),
        field="validation_surface.kind",
        vocabulary=_ALL_VALIDATION_SURFACE_KINDS,
        label="validation_surface",
    )
    if kind == "worktree_local_sqlite":
        prov = _require_dict(obj.get("provisioning"), field="validation_surface.provisioning")
        extra_prov = set(prov.keys()) - {"path", "recipe"}
        if extra_prov:
            raise MigrationModelCapabilityError(
                f"validation_surface.provisioning has unknown keys for worktree_local_sqlite: "
                f"{sorted(extra_prov)}"
            )
        path = prov.get("path")
        recipe = prov.get("recipe")
        if not isinstance(path, str) or not path:
            raise MigrationModelCapabilityError(
                "validation_surface.provisioning.path must be a non-empty string"
            )
        if not isinstance(recipe, str) or not recipe:
            raise MigrationModelCapabilityError(
                "validation_surface.provisioning.recipe must be a non-empty string"
            )
        if recipe not in _KNOWN_VALIDATION_RECIPES:
            raise MigrationModelCapabilityError(
                f"validation_surface.provisioning.recipe '{recipe}' is not a "
                f"recognized recipe; expected one of "
                f"{sorted(_KNOWN_VALIDATION_RECIPES)}"
            )
        return {"kind": kind, "provisioning": {"path": path, "recipe": recipe}}
    if kind == "external_validation":
        prov = _require_dict(obj.get("provisioning"), field="validation_surface.provisioning")
        extra_prov = set(prov.keys()) - {"trigger", "evidence_contract"}
        if extra_prov:
            raise MigrationModelCapabilityError(
                "validation_surface.provisioning has unknown keys for "
                f"external_validation: {sorted(extra_prov)}"
            )
        for required in ("trigger", "evidence_contract"):
            if not isinstance(prov.get(required), str) or not prov.get(required):
                raise MigrationModelCapabilityError(
                    f"validation_surface.provisioning.{required} must be a "
                    "non-empty string"
                )
        return {
            "kind": kind,
            "provisioning": {k: prov[k] for k in ("trigger", "evidence_contract")},
        }
    raise MigrationModelCapabilityError(
        f"validation_surface.kind '{kind}' is recognized but the combination "
        f"is not yet supported in this slice"
    )


def _validate_runner(value: Any) -> Dict[str, Any]:
    obj = _require_dict(value, field="runner")
    extra = set(obj.keys()) - {"kind", "config"}
    if extra:
        raise MigrationModelCapabilityError(
            f"runner has unknown keys: {sorted(extra)}"
        )
    kind = _require_kind(
        obj.get("kind"),
        field="runner.kind",
        vocabulary=_ALL_RUNNER_KINDS,
        label="runner",
    )
    if kind == RUNNER_KIND_GOVERNED_MODULE:
        cfg = _require_dict(obj.get("config"), field="runner.config")
        extra_cfg = set(cfg.keys()) - {"modules_dir", "connection_env_var"}
        if extra_cfg:
            raise MigrationModelCapabilityError(
                f"runner.config has unknown keys for governed_migration_module: "
                f"{sorted(extra_cfg)}"
            )
        modules_dir = cfg.get("modules_dir")
        if not isinstance(modules_dir, str) or not modules_dir:
            raise MigrationModelCapabilityError(
                "runner.config.modules_dir must be a non-empty string"
            )
        conn_env = cfg.get("connection_env_var", DEFAULT_CONNECTION_ENV_VAR)
        if not isinstance(conn_env, str) or not conn_env:
            raise MigrationModelCapabilityError(
                "runner.config.connection_env_var must be a non-empty string"
            )
        return {
            "kind": kind,
            "config": {"modules_dir": modules_dir, "connection_env_var": conn_env},
        }
    raise MigrationModelCapabilityError(
        f"runner.kind '{kind}' is recognized but the combination "
        f"is not yet supported in this slice"
    )


def _validate_model(name: str, raw: Any) -> Dict[str, Any]:
    obj = _require_dict(raw, field=f"models[{name!r}]")
    extra = set(obj.keys()) - {"authoritative_db", "validation_surface", "runner"}
    if extra:
        raise MigrationModelCapabilityError(
            f"models[{name!r}] has unknown keys: {sorted(extra)}"
        )
    missing = {"authoritative_db", "validation_surface", "runner"} - set(obj.keys())
    if missing:
        raise MigrationModelCapabilityError(
            f"models[{name!r}] missing required keys: {sorted(missing)}"
        )
    authoritative_db = _validate_authoritative_db(obj["authoritative_db"])
    validation_surface = _validate_validation_surface(obj["validation_surface"])
    runner = _validate_runner(obj["runner"])

    pairing = (
        authoritative_db["kind"],
        validation_surface["kind"],
        runner["kind"],
    )
    if pairing not in _LIVE_PAIRINGS:
        raise MigrationModelCapabilityError(
            f"models[{name!r}] combination "
            f"authoritative_db.kind={pairing[0]}, validation_surface.kind={pairing[1]}, "
            f"runner.kind={pairing[2]} is recognized but not yet supported in this slice"
        )

    return {
        "authoritative_db": authoritative_db,
        "validation_surface": validation_surface,
        "runner": runner,
    }


def validate(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a ``migration_model`` capability settings payload.

    Returns a normalized dict with canonical key ordering, stable field
    shapes, and ``connection_env_var`` defaulted to ``YOKE_PG_DSN`` when
    the governed runner omits it.
    """
    obj = _require_dict(payload, field="migration_model capability settings")
    extra = set(obj.keys()) - {"default_model", "models"}
    if extra:
        raise MigrationModelCapabilityError(
            f"migration_model capability has unknown keys: {sorted(extra)}"
        )

    models_raw = obj.get("models")
    if not isinstance(models_raw, dict) or not models_raw:
        raise MigrationModelCapabilityError(
            "migration_model capability requires a non-empty 'models' dict"
        )

    models_out: Dict[str, Any] = {}
    for name, spec in models_raw.items():
        _require_slug(name, field=f"models key")
        if name in models_out:
            raise MigrationModelCapabilityError(
                f"models has duplicate name '{name}'"
            )
        models_out[name] = _validate_model(name, spec)

    result: Dict[str, Any] = {"models": models_out}

    default_model = obj.get("default_model")
    if default_model is not None:
        _require_slug(default_model, field="default_model")
        if default_model not in models_out:
            raise MigrationModelCapabilityError(
                f"default_model '{default_model}' is not declared in models"
            )
        result["default_model"] = default_model

    return result


def canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_json_string(raw: str) -> str:
    """Parse *raw* as JSON, validate, and return compact canonical JSON."""
    if raw is None or raw == "":
        raise MigrationModelCapabilityError(
            "migration_model capability settings payload is empty"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationModelCapabilityError(f"malformed JSON: {exc}") from exc
    return canonical_json(validate(payload))
