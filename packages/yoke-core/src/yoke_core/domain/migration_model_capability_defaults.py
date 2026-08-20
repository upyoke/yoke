"""Project-neutral construction and lookup helpers for migration models."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from yoke_core.domain.migration_ledger_contract import runner_config_ledger

#: Default model key in a governed-postgres seed. The spelling collides with
#: the unresolved execution-lane sentinel; declared membership is what
#: distinguishes a real model from a lane leaking into ``model_name``.
DEFAULT_MODEL_NAME = "primary"


def governed_postgres_seed(
    location: Mapping[str, Any],
    *,
    modules_dir: str,
    ledger: Mapping[str, Any],
    connection_env_var: str,
    artifact_version_env_var: str | None = None,
) -> Dict[str, Any]:
    """Return a governed Postgres migration model for ``location``.

    Every project supplies its own history and ledger identifiers.  There is
    deliberately no ambient Yoke path/table fallback: a project-neutral seed
    that inherited Yoke's concrete names would validate while pointing at the
    wrong code and database evidence.
    """
    runner_config: Dict[str, Any] = {
        "modules_dir": modules_dir,
        "connection_env_var": connection_env_var,
        "ledger": runner_config_ledger(ledger, ValueError),
    }
    if artifact_version_env_var is not None:
        runner_config["artifact_version_env_var"] = artifact_version_env_var
    return {
        "default_model": DEFAULT_MODEL_NAME,
        "models": {
            DEFAULT_MODEL_NAME: {
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
                    "config": runner_config,
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
