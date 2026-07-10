"""Canonical cloud-runtime machine-config contract.

Connections are keyed by env label under ``connections``; ``active_env``
names the machine-global default. Per-command routing (``--env`` /
``YOKE_ENV``) selects any configured env without rewriting the file
(decision record: ``docs/archive/decisions/machine-config-env-connections.md``).
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    canonical_project_entry as canonical_project_entry,
    canonical_project_map as canonical_project_map,
    checkout_path_candidates as checkout_path_candidates,
    normalize_project_id as normalize_project_id,
    project_entry_for_checkout as project_entry_for_checkout,
    _error,
    _is_nonempty_str,
    _nonempty_str,
    _strip_worktree_path as _strip_worktree_path,
    _validate_project_entry,
)
from yoke_contracts.machine_config.credential_sources import (
    CREDENTIAL_KIND_AWS_SECRETS_MANAGER as CREDENTIAL_KIND_AWS_SECRETS_MANAGER,
    CREDENTIAL_KIND_DSN_FILE as CREDENTIAL_KIND_DSN_FILE,
    CREDENTIAL_KIND_ENV as CREDENTIAL_KIND_ENV,
    CREDENTIAL_KIND_TOKEN_FILE as CREDENTIAL_KIND_TOKEN_FILE,
    CREDENTIAL_KINDS as CREDENTIAL_KINDS,
    TOKEN_CREDENTIAL_KINDS,
    validate_credential_source as _validate_credential_source_impl,
)
from yoke_contracts.machine_config.schema_transport import (
    DEFAULT_TRANSPORT as DEFAULT_TRANSPORT, POSTGRES_TRANSPORTS,
    PRODUCT_CLIENT_TRANSPORTS as PRODUCT_CLIENT_TRANSPORTS,
    TRANSPORTS, TRANSPORT_HTTPS,
)
from yoke_contracts.machine_config.schema_github import (
    DEFAULT_GITHUB_API_URL as DEFAULT_GITHUB_API_URL,
    DEFAULT_GITHUB_WEB_URL as DEFAULT_GITHUB_WEB_URL,
    github_config as github_config, has_github_config,
    GITHUB_AUTH_KIND_USER_AUTHORIZATION as GITHUB_AUTH_KIND_USER_AUTHORIZATION,
    GITHUB_AUTH_STATUSES as GITHUB_AUTH_STATUSES,
    normalize_github_payload, validate_github_config,
)
from yoke_contracts.machine_config.schema_connections import (
    PROD_FLAG_KEY, connection_is_prod as connection_is_prod, local_postgres_envs,
)

SCHEMA_VERSION = 1
ENV_OVERRIDE = "YOKE_ENV"
DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_BOARD_PATH = ".yoke/BOARD.md"
DEFAULT_CACHE_DIR_NAME = "cache"
DEFAULT_TEMP_DIR_NAME = "tmp"
DEFAULT_TEMP_ROOT = "~/.yoke/tmp"
DEFAULT_CACHE_ROOT = "~/.yoke/cache"
SECRETS_DIR_NAME = "secrets"
# SSH local-forward parameters the readiness self-heal needs; a declared
# ``connections.<env>.postgres.tunnel`` block must carry all of them.
TUNNEL_REQUIRED_KEYS = ("bastion", "identity_file", "remote_host", "remote_port")

class MachineConfigContractError(RuntimeError):
    """Raised when the selected machine config cannot be used."""

from yoke_contracts.machine_config.schema_example import (  # noqa: E402
    canonical_example_payload as canonical_example_payload,
    canonical_example_text as canonical_example_text,
)
from yoke_contracts.machine_config.schema_product import (  # noqa: E402
    product_client_connection as product_client_connection,
)


def normalize_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a normalized copy with contract defaults filled."""
    raw = dict(payload or {})
    normalized: dict[str, Any] = dict(raw)
    normalized.setdefault("schema_version", SCHEMA_VERSION)
    normalized["temp_root"] = _nonempty_str(raw.get("temp_root"),
                                            DEFAULT_TEMP_ROOT)
    normalized["cache_dir"] = _nonempty_str(raw.get("cache_dir"),
                                           DEFAULT_CACHE_ROOT)
    projects = raw.get("projects")
    settings = raw.get("settings")
    connections = raw.get("connections")
    normalized["projects"] = dict(projects) if isinstance(projects, Mapping) else {}
    normalized["settings"] = dict(settings) if isinstance(settings, Mapping) else {}
    normalize_github_payload(raw, normalized)
    if isinstance(connections, Mapping):
        normalized["connections"] = {
            str(env): dict(entry) if isinstance(entry, Mapping) else entry
            for env, entry in connections.items()
        }
    return normalized

def validate_payload(
    payload: Mapping[str, Any] | None,
    *,
    explicit_env: str | None = None,
) -> list[ValidationIssue]:
    """Validate the machine-config payload shape."""
    if not isinstance(payload, Mapping):
        return [_error("root_object", "machine config must be a JSON object")]
    raw: Mapping[str, Any] = payload
    issues: list[ValidationIssue] = []
    issues.extend(validate_github_config(raw))
    github_available = has_github_config(raw)
    if raw.get("schema_version") != SCHEMA_VERSION:
        issues.append(_error("schema_version", "schema_version must be 1",
                             path="schema_version"))
    connections = raw.get("connections")
    if not isinstance(connections, Mapping) or not connections:
        if not github_available:
            issues.append(_error(
                "connections_required",
                "connections must map env labels to connection objects",
                path="connections",
                hint="Add connections or start from `yoke config example`.",
            ))
        connections = {}
    else:
        for env_label, entry in connections.items():
            if not _is_nonempty_str(env_label):
                issues.append(_error("connection_env_label_invalid",
                                     "connection env labels must be non-empty strings",
                                     path="connections"))
                continue
            if not isinstance(entry, Mapping):
                issues.append(_error("connection_entry_invalid",
                                     f"connections.{env_label} must be an object",
                                     path=f"connections.{env_label}"))
                continue
            issues.extend(_validate_connection(str(env_label), entry))
    active = raw.get("active_env")
    if not _is_nonempty_str(active) and (connections or not github_available):
        issues.append(_error(
            "active_env_required", "active_env must name the default env",
            path="active_env", hint="Set it with `yoke env use <env>`."))
    elif connections and str(active) not in connections:
        issues.append(_error(
            "active_env_unknown",
            f"active_env {str(active)!r} has no entry in connections "
            f"(configured: {sorted(map(str, connections))})",
            path="active_env"))
    requested = (explicit_env or "").strip()
    if requested and connections and requested not in connections:
        issues.append(_error(
            "env_unknown",
            f"requested env {requested!r} has no entry in connections "
            f"(configured: {sorted(map(str, connections))})",
            path="connections"))
    for key in ("temp_root", "cache_dir"):
        value = raw.get(key)
        if value is not None and not _is_nonempty_str(value):
            issues.append(_error(f"{key}_invalid",
                                 f"{key} must be a non-empty string", path=key))
    projects = raw.get("projects", {})
    if projects is not None and not isinstance(projects, Mapping):
        issues.append(_error("projects_invalid",
                             "projects must map checkout paths to entries",
                             path="projects"))
    elif isinstance(projects, Mapping):
        for checkout, entry in projects.items():
            issues.extend(_validate_project_entry(checkout, entry))
    settings = raw.get("settings", {})
    if settings is not None and not isinstance(settings, Mapping):
        issues.append(_error(
            "settings_invalid", "settings must be an object", path="settings"))
    return issues

def selected_env(payload: Mapping[str, Any], explicit_env: str | None = None) -> str:
    """Resolve env precedence: explicit, ``YOKE_ENV``, then ``active_env``."""
    requested = (explicit_env or "").strip() or os.environ.get(ENV_OVERRIDE, "").strip()
    configured = str(payload.get("active_env") or "").strip()
    selected = requested or configured
    if not selected:
        raise MachineConfigContractError(
            "active env is not configured; run `yoke env use <env>` or pass --env"
        )
    return selected

def active_connection(
    payload: Mapping[str, Any],
    *,
    explicit_env: str | None = None,
) -> Mapping[str, Any]:
    """Return the selected env's connection or raise a setup error.

    The returned mapping carries the resolved env label under ``env``.
    """
    env_name = selected_env(payload, explicit_env=explicit_env)
    connections = payload.get("connections")
    if not isinstance(connections, Mapping) or not connections:
        raise MachineConfigContractError(
            "connections must map env labels to connection objects"
        )
    entry = connections.get(env_name)
    if not isinstance(entry, Mapping):
        raise MachineConfigContractError(
            f"env {env_name!r} has no connection in machine config "
            f"(configured: {sorted(map(str, connections))}); add it with "
            "`yoke connection set` or pick one with `yoke env use`"
        )
    transport = str(entry.get("transport") or "").strip()
    if transport not in TRANSPORTS:
        raise MachineConfigContractError(
            f"connections.{env_name}.transport must be one of {sorted(TRANSPORTS)}"
        )
    resolved = dict(entry)
    resolved["env"] = env_name
    return resolved

def _validate_connection(
    env_label: str,
    connection: Mapping[str, Any],
) -> list[ValidationIssue]:
    prefix = f"connections.{env_label}"
    issues: list[ValidationIssue] = []
    transport = connection.get("transport")
    if not _is_nonempty_str(transport) or str(transport) not in TRANSPORTS:
        issues.append(_error("transport_invalid",
                             f"{prefix}.transport must be one of {sorted(TRANSPORTS)}",
                             path=f"{prefix}.transport"))
    source = connection.get("credential_source")
    if not isinstance(source, Mapping):
        issues.append(_error("credential_source_required",
                             f"{prefix}.credential_source must be an object",
                             path=f"{prefix}.credential_source"))
    else:
        issues.extend(_validate_credential_source(source, prefix=prefix))
    if PROD_FLAG_KEY in connection and not isinstance(connection.get(PROD_FLAG_KEY), bool):
        issues.append(_error(
            "prod_flag_invalid",
            f"{prefix}.{PROD_FLAG_KEY} must be a boolean when present",
            path=f"{prefix}.{PROD_FLAG_KEY}",
        ))
    if str(transport) in POSTGRES_TRANSPORTS:
        postgres = connection.get("postgres")
        if postgres is not None and not isinstance(postgres, Mapping):
            issues.append(_error("postgres_invalid",
                                 f"{prefix}.postgres must be an object",
                                 path=f"{prefix}.postgres"))
        elif isinstance(postgres, Mapping):
            issues.extend(_validate_tunnel(postgres.get("tunnel"), prefix=prefix))
    if str(transport) == TRANSPORT_HTTPS:
        if not _is_nonempty_str(connection.get("api_url")):
            issues.append(_error("api_url_required",
                                 "https transport requires api_url",
                                 path=f"{prefix}.api_url"))
        kind = source.get("kind") if isinstance(source, Mapping) else None
        if kind not in TOKEN_CREDENTIAL_KINDS:
            issues.append(_error(
                "https_credential_kind_invalid",
                "https transport requires credential_source.kind 'token_file'",
                path=f"{prefix}.credential_source.kind"))
    return issues

def _validate_tunnel(
    tunnel: Any,
    *,
    prefix: str,
) -> list[ValidationIssue]:
    """A declared tunnel block must be complete or the self-heal is dead."""
    if tunnel is None:
        return []
    if not isinstance(tunnel, Mapping):
        return [_error("tunnel_invalid",
                       f"{prefix}.postgres.tunnel must be an object",
                       path=f"{prefix}.postgres.tunnel")]
    missing = [key for key in TUNNEL_REQUIRED_KEYS if not tunnel.get(key)]
    if missing:
        return [_error(
            "tunnel_incomplete",
            f"{prefix}.postgres.tunnel is missing {', '.join(missing)}; "
            "an incomplete tunnel block disables connected-env self-heal",
            path=f"{prefix}.postgres.tunnel",
            hint=f"Declare all of: {', '.join(TUNNEL_REQUIRED_KEYS)}.")]
    return []


def env_override_teaching(
    payload: Mapping[str, Any] | None,
    *,
    selected_env: str,
    transport: str,
    command: str | None = None,
) -> str:
    """Setup-error text for a local-postgres-only operation under a non-local
    selected env: why it failed, the configured local-postgres envs, and the
    one-line override recipe.
    """
    envs = local_postgres_envs(payload)
    why = (
        f"connected env {selected_env!r} (transport {transport}) has no local "
        "Postgres; this operation requires a local-postgres env."
    )
    if not envs:
        return (
            f"{why} No local-postgres env is configured on this machine; add "
            "one under connections in ~/.yoke/config.json "
            "(see `yoke config example`)."
        )
    recipe_env = envs[0]
    recipe_cmd = command if command is not None else _invocation_recipe()
    return (
        f"{why} Run: {ENV_OVERRIDE}={recipe_env} {recipe_cmd} "
        f"(configured local-postgres envs: {', '.join(envs)}; `yoke` "
        f"subcommands also accept --env {recipe_env})."
    )


def _invocation_recipe(
    argv: list[str] | None = None,
    main_spec_name: str | None = None,
) -> str:
    """Reconstruct the current invocation for the override recipe line."""
    import shlex
    import sys

    args = list(sys.argv) if argv is None else list(argv)
    if main_spec_name is None:
        spec = getattr(sys.modules.get("__main__"), "__spec__", None)
        main_spec_name = getattr(spec, "name", "") or ""
    module = main_spec_name.removesuffix(".__main__")
    if module and module != "__main__":
        prefix = f"python3 -m {module}"
    else:
        prefix = Path(args[0]).name if args and args[0] else "<command>"
    tail = " ".join(shlex.quote(arg) for arg in args[1:])
    return f"{prefix} {tail}".strip()


def _validate_credential_source(
    source: Mapping[str, Any],
    *,
    prefix: str,
) -> list[ValidationIssue]:
    return _validate_credential_source_impl(source, prefix=prefix)
