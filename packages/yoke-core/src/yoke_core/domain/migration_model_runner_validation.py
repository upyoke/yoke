"""Validate the ``runner`` block of one ``migration_model`` model declaration.

The error class is injected so the refusal keeps the capability validator's
own exception type without this module importing the validator.
"""

from __future__ import annotations

from typing import Any, Dict

RUNNER_KIND_GOVERNED_MODULE = "governed_migration_module"
_GOVERNED_CONFIG_KEYS = frozenset(
    {"modules_dir", "connection_env_var", "artifact_version_env_var", "ledger"}
)


def validate_runner(
    value: Any, error: type, *, runner_kinds: frozenset
) -> Dict[str, Any]:
    """Normalize a model's runner declaration, raising *error* on refusal."""
    if not isinstance(value, dict):
        raise error(f"runner must be a JSON object; got {type(value).__name__}")
    extra = set(value) - {"kind", "config"}
    if extra:
        raise error(f"runner has unknown keys: {sorted(extra)}")
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise error(f"runner.kind must be a string; got {type(kind).__name__}")
    if kind not in runner_kinds:
        raise error(
            f"runner.kind '{kind}' is not a recognized runner kind; "
            f"expected one of {sorted(runner_kinds)}"
        )
    if kind != RUNNER_KIND_GOVERNED_MODULE:
        raise error(
            f"runner.kind '{kind}' is recognized but the combination "
            f"is not yet supported in this slice"
        )
    cfg = value.get("config")
    if not isinstance(cfg, dict):
        raise error(f"runner.config must be a JSON object; got {type(cfg).__name__}")
    extra_cfg = set(cfg) - _GOVERNED_CONFIG_KEYS
    if extra_cfg:
        raise error(
            "runner.config has unknown keys for governed_migration_module: "
            f"{sorted(extra_cfg)}"
        )
    modules_dir = cfg.get("modules_dir")
    if not isinstance(modules_dir, str) or not modules_dir:
        raise error("runner.config.modules_dir must be a non-empty string")
    conn_env = cfg.get("connection_env_var")
    if not isinstance(conn_env, str) or not conn_env:
        raise error("runner.config.connection_env_var must be a non-empty string")
    if "ledger" not in cfg:
        raise error(
            "runner.config.ledger is required; a governed migration "
            "model must declare membership, content-digest, and "
            "serving-floor columns"
        )
    from yoke_core.domain import migration_ledger_contract

    config: Dict[str, Any] = {
        "modules_dir": modules_dir,
        "connection_env_var": conn_env,
        "ledger": migration_ledger_contract.runner_config_ledger(cfg["ledger"], error),
    }
    artifact_version_env = cfg.get("artifact_version_env_var")
    if artifact_version_env is not None:
        if not isinstance(artifact_version_env, str) or not artifact_version_env:
            raise error(
                "runner.config.artifact_version_env_var must be a "
                "non-empty string when present"
            )
        config["artifact_version_env_var"] = artifact_version_env
    return {"kind": kind, "config": config}


__all__ = ["RUNNER_KIND_GOVERNED_MODULE", "validate_runner"]
