"""Model construction and lookup helpers for migration_model capability."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from yoke_core.domain.migration_model_capability_validation import (
    DEFAULT_CONNECTION_ENV_VAR,
)

#: Repo-relative home of the governed migration modules package.
DEFAULT_MODULES_DIR = "packages/yoke-core/src/yoke_core/domain/migrations"


def governed_postgres_seed(location: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a governed Postgres migration model for ``location``.

    Database authority belongs to the caller's current capability settings;
    this helper deliberately has no environment-specific fallback.
    """
    return {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "postgres",
                    "location": dict(location),
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
                        "modules_dir": DEFAULT_MODULES_DIR,
                        "connection_env_var": DEFAULT_CONNECTION_ENV_VAR,
                        # Membership, so a skipped entry stays pending and a
                        # rollback cannot report itself current.
                        "ledger": {
                            "table": "applied_migrations",
                            "entry_column": "migration_name",
                            "semantics": "membership",
                            "serving_floor_column": "minimum_serving_version",
                        },
                    },
                },
            },
        },
    }


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
