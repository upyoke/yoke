"""Validator and defaults for the ``migration_model`` project-capability type.

Per-project declaration of the governed-DB environment.  One capability row
per project; ``settings.models`` is a keyed dict of model declarations.
Model names live inside ``settings.models`` — the ``project_capabilities.type``
column stays the singular, unsuffixed string ``migration_model``.

Schema shape::

    {
        "default_model": "primary",          # optional; when present, must exist in models
        "models": {
            "<slug>": {
                "authoritative_db":  {"kind": "...", "location": {...}},
                "validation_surface": {"kind": "...", "provisioning": {...}},
                "runner":            {"kind": "...", "config": {...}}
            },
            ...
        }
    }

**Wired pairings.** Legacy ``sqlite_file`` authoritative DBs pair with
``worktree_local_sqlite`` validation; Postgres authoritative DBs pair with an
``external_validation`` evidence contract and the governed Python module
runner. Recipe vocabulary is constrained to the validation-recipe registry
(:mod:`yoke_core.domain.worktree_validation_recipes`); runner-kind
vocabulary to the runner dispatch registry
(:mod:`yoke_core.domain.migration_apply_runners`). Future slices unlock
additional pairings additively.
"""

from __future__ import annotations

import json

from yoke_core.domain.migration_apply_runners import UnknownRunnerKind
from yoke_core.domain.migration_model_capability_defaults import (
    governed_postgres_seed, resolve_model,
)
from yoke_core.domain.migration_model_capability_validation import (
    CAPABILITY_TYPE, DEFAULT_CONNECTION_ENV_VAR,
    MigrationModelCapabilityError,
    RECIPE_WEBAPP_SQLITE_EMPTY,
    RUNNER_KIND_GOVERNED_MODULE,
    validate,
)
from yoke_core.domain.worktree_validation_recipes import UnknownValidationRecipe


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_json_string(raw: str) -> str:
    """Parse, validate, and return compact canonical capability JSON."""
    if raw is None or raw == "":
        raise MigrationModelCapabilityError(
            "migration_model capability settings payload is empty"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationModelCapabilityError(f"malformed JSON: {exc}") from exc
    return canonical_json(validate(payload))

__all__ = [
    "CAPABILITY_TYPE",
    "DEFAULT_CONNECTION_ENV_VAR",
    "MigrationModelCapabilityError",
    "RECIPE_WEBAPP_SQLITE_EMPTY",
    "RUNNER_KIND_GOVERNED_MODULE",
    "UnknownRunnerKind",
    "UnknownValidationRecipe",
    "canonical_json",
    "governed_postgres_seed",
    "resolve_model",
    "validate",
    "validate_json_string",
]
