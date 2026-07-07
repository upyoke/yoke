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

from yoke_core.domain.migration_apply_runners import UnknownRunnerKind
from yoke_core.domain.migration_model_capability_defaults import (
    YOKE_PRIMARY_SEED_JSON, resolve_model, yoke_primary_postgres_seed,
    yoke_primary_seed,
)
from yoke_core.domain.migration_model_capability_validation import (
    CAPABILITY_TYPE, DEFAULT_CONNECTION_ENV_VAR,
    MigrationModelCapabilityError,
    RECIPE_WEBAPP_SQLITE_EMPTY,
    RUNNER_KIND_GOVERNED_MODULE,
    canonical_json, validate, validate_json_string,
)
from yoke_core.domain.worktree_validation_recipes import UnknownValidationRecipe

__all__ = [
    "CAPABILITY_TYPE",
    "DEFAULT_CONNECTION_ENV_VAR",
    "MigrationModelCapabilityError",
    "RECIPE_WEBAPP_SQLITE_EMPTY",
    "RUNNER_KIND_GOVERNED_MODULE",
    "YOKE_PRIMARY_SEED_JSON",
    "UnknownRunnerKind",
    "UnknownValidationRecipe",
    "canonical_json",
    "resolve_model",
    "yoke_primary_postgres_seed",
    "yoke_primary_seed",
    "validate",
    "validate_json_string",
]
