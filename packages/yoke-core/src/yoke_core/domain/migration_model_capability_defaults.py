"""Seed defaults and model lookup helpers for migration_model capability."""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

from yoke_core.domain.migration_model_capability_validation import (
    DEFAULT_CONNECTION_ENV_VAR, canonical_json,
)

def yoke_primary_seed() -> Dict[str, Any]:
    """Return the canonical Yoke-project ``migration_model`` capability seed.

    Single source of truth for the Yoke-project bootstrap shape (§11.4).
    Used by ``projects_restart.cmd_init`` when seeding the default
    capabilities and by tests that assert on the bootstrap seed.
    """
    return copy.deepcopy({
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "postgres",
                    "location": {
                        "stack": "yoke-prod",
                        "state_backend": "s3://yoke-pulumi-state?region=us-east-1",
                        "region": "us-east-1",
                        "database_name": "yoke_prod",
                        "endpoint_output": "databaseClusterEndpoint",
                        "secret_arn_output": "databaseSecretArn",
                    },
                },
                "validation_surface": {
                    "kind": "external_validation",
                    "provisioning": {
                        "trigger": "postgres_authority",
                        "evidence_contract": "aurora_connected_environment",
                    },
                },
                "runner": {
                    "kind": "governed_migration_module",
                    "config": {
                        "modules_dir": "runtime/api/domain/migrations",
                        "connection_env_var": DEFAULT_CONNECTION_ENV_VAR,
                    },
                },
            },
        },
    })


def yoke_primary_postgres_seed(location: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the Yoke primary model with Postgres as authority.

    The caller supplies the location block so this helper does not bake Yoke
    prod stack literals into generic seed code.
    """
    seed = yoke_primary_seed()
    seed["models"]["primary"]["authoritative_db"] = {
        "kind": "postgres",
        "location": dict(location),
    }
    return seed


YOKE_PRIMARY_SEED_JSON = canonical_json(yoke_primary_seed())


def resolve_model(
    capability_settings: Mapping[str, Any], model_name: str
) -> Dict[str, Any]:
    """Look up a validated model block by name.

    ``capability_settings`` must have already passed :func:`validate`.  Raises
    :class:`KeyError` when the name is not declared.
    """
    models = capability_settings.get("models") or {}
    if model_name not in models:
        raise KeyError(f"model '{model_name}' is not declared")
    return dict(models[model_name])
