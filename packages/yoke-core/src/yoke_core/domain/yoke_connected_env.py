"""Connected-environment authority resolution for local Yoke runtimes.

The binding lives in the machine-local ``~/.yoke/config.json`` file. It is
secret-bearing in cloud-runtime v0 because it can carry credential references and
machine-local tokens. Postgres credential env vars can still override the
ambient project binding.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain import machine_config
from yoke_contracts.machine_config import schema as contract

BINDING_RELATIVE_PATH = "~/.yoke/config.json"
DISABLE_ENV = "YOKE_CONNECTED_ENV_DISABLE"
PYTEST_ENABLE_ENV = "YOKE_CONNECTED_ENV_ENABLE_IN_PYTEST"
SQLITE_GUARD_PREFIX = "SQLite authority retired/guarded"


class ConnectedEnvError(RuntimeError):
    """Raised when a connected-env binding exists but is invalid/unusable."""


class ConnectedEnvNotLocalPostgres(ConnectedEnvError):
    """The selected env has no local Postgres (e.g. https transport).

    The message is the full operator teaching: why the operation needs a
    local-postgres env, which envs are configured, and the
    ``YOKE_ENV=<env> <command>`` override recipe. Callers surface it as-is
    instead of wrapping it in the generic DSN setup error.
    """


@dataclass(frozen=True)
class ConnectedEnv:
    binding_path: Path
    project: str
    project_id: Optional[int]
    environment: str
    backend: str
    config: Mapping[str, Any]

    @property
    def repo_root(self) -> Path:
        return Path.cwd()

    @property
    def credential_source(self) -> Mapping[str, Any]:
        value = self.config.get("credential_source")
        return value if isinstance(value, Mapping) else {}

    @property
    def authority(self) -> Mapping[str, Any]:
        value = self.config.get("authority")
        return value if isinstance(value, Mapping) else {}

    @property
    def connection(self) -> Mapping[str, Any]:
        value = self.config.get("postgres")
        return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ResolvedDsn:
    dsn: str
    redacted_dsn: str
    evidence: Mapping[str, Any]
    process_env: Mapping[str, str]


def find_binding(start: Optional[Path] = None) -> Optional[Path]:
    """Return the selected machine connected-env binding, if present."""
    if os.environ.get(DISABLE_ENV) == "1":
        return None
    in_pytest = (
        os.environ.get("PYTEST_CURRENT_TEST")
        or "pytest" in __import__("sys").modules
    )
    if start is None and in_pytest and os.environ.get(PYTEST_ENABLE_ENV) != "1":
        return None
    candidate = machine_config.config_path()
    return candidate if candidate.is_file() else None


def load_active(start: Optional[Path] = None) -> Optional[ConnectedEnv]:
    """Return the active connected environment, or ``None`` when unbound."""
    binding = find_binding(start)
    if not binding:
        return None
    try:
        raw = machine_config.load_config(binding)
        env_cfg = machine_config.active_connection(binding)
    except (machine_config.MachineConfigError,
            contract.MachineConfigContractError) as exc:
        raise ConnectedEnvError(str(exc)) from exc
    issues = contract.validate_payload(raw)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise ConnectedEnvError("; ".join(issue.message for issue in errors))
    env_name = _required_str(env_cfg, "env")
    transport = _required_str(env_cfg, "transport").lower()
    backend = "postgres" if transport in contract.POSTGRES_TRANSPORTS else transport
    project_id = machine_config.project_id(Path.cwd())
    project = str(project_id or "")
    return ConnectedEnv(
        binding_path=binding,
        project=project,
        project_id=project_id,
        environment=env_name,
        backend=backend,
        config=env_cfg,
    )


def connected_backend(start: Optional[Path] = None) -> Optional[str]:
    env = load_active(start)
    return env.backend if env else None


def resolve_postgres_dsn(
    *,
    start: Optional[Path] = None,
    dsn_env: str,
    dsn_file_env: str,
) -> ResolvedDsn:
    """Resolve the active connected-env Postgres DSN and redacted evidence."""
    env = load_active(start)
    if not env:
        raise ConnectedEnvError("no connected environment binding found")
    if env.backend != "postgres":
        raise ConnectedEnvNotLocalPostgres(contract.env_override_teaching(
            machine_config.load_config(env.binding_path),
            selected_env=env.environment,
            transport=env.backend,
        ))
    source = env.credential_source
    kind = _required_str(source, "kind")
    if kind == "dsn_file":
        dsn_path = _credential_path(env, _required_str(source, "path"))
        if not dsn_path.is_file():
            raise ConnectedEnvError(
                f"connected-env credential file missing: {dsn_path}"
            )
        dsn = dsn_path.read_text(encoding="utf-8").strip()
        if not dsn:
            raise ConnectedEnvError(
                f"connected-env credential file is empty: {dsn_path}"
            )
        redacted = _redacted_dsn(dsn)
        return ResolvedDsn(
            dsn=dsn,
            redacted_dsn=redacted,
            evidence={
                "project": env.project,
                "environment": env.environment,
                "backend": env.backend,
                "credential_source": {"kind": kind, "path": str(dsn_path)},
                "dsn": redacted,
            },
            process_env={dsn_file_env: str(dsn_path)},
        )
    if kind == "env":
        name = str(source.get("name") or dsn_env)
        dsn = os.environ.get(name, "").strip()
        if not dsn:
            raise ConnectedEnvError(
                f"connected-env credential env var missing: {name}"
            )
        redacted = _redacted_dsn(dsn)
        return ResolvedDsn(
            dsn=dsn,
            redacted_dsn=redacted,
            evidence={
                "project": env.project,
                "environment": env.environment,
                "backend": env.backend,
                "credential_source": {"kind": kind, "name": name},
                "dsn": redacted,
            },
            process_env={dsn_env: dsn},
        )
    if kind == "aws_secrets_manager":
        from yoke_core.domain.yoke_cloud_db_authority import (
            PostgresAuthorityLocation,
            resolve_declared_dsn,
        )

        authority = _required_mapping(env.config, "authority")
        location = PostgresAuthorityLocation.from_mapping(
            _required_mapping(authority, "location")
        )
        infra_dir = env.repo_root / _required_str(authority, "infra_dir")
        connection = env.connection
        dsn, evidence = resolve_declared_dsn(
            infra_dir=infra_dir,
            location=location,
            host_override=_optional_str(connection, "host"),
            port_override=_optional_int(connection, "port"),
        )
        return ResolvedDsn(
            dsn=dsn,
            redacted_dsn=str(evidence.get("dsn") or _redacted_dsn(dsn)),
            evidence={
                "project": env.project,
                "environment": env.environment,
                "backend": env.backend,
                "credential_source": {"kind": kind},
                "connection": _connection_evidence(connection),
                **dict(evidence),
            },
            process_env={dsn_env: dsn},
        )
    raise ConnectedEnvError(f"unsupported credential_source.kind: {kind!r}")


def process_env_overrides(
    *,
    dsn_env: str,
    dsn_file_env: str,
    start: Optional[Path] = None,
) -> dict[str, str]:
    """Return credential env vars a child process needs for connected authority."""
    env = load_active(start)
    if not env:
        return {}
    if env.backend == "postgres":
        return dict(
            resolve_postgres_dsn(
                start=start, dsn_env=dsn_env, dsn_file_env=dsn_file_env
            ).process_env
        )
    return {}


def sqlite_guard_reason(
    *,
    yoke_db_env: str = "YOKE_DB",
    start: Optional[Path] = None,
) -> Optional[str]:
    """Return a guard reason when raw SQLite authority must not be used."""
    from yoke_core.domain.yoke_connected_env_sqlite import (
        sqlite_guard_reason_for_env,
    )

    return sqlite_guard_reason_for_env(load_active(start), yoke_db_env=yoke_db_env)


def sqlite_guard_message(reason: str) -> str:
    return (
        f"{SQLITE_GUARD_PREFIX}: {reason} selects Postgres authority; "
        "refusing to open or mutate data/yoke.db. Route through "
        "yoke_core.domain.db_backend.connect() or provide an explicit "
        "test fixture YOKE_DB."
    )


def _credential_path(env: ConnectedEnv, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = env.binding_path.parent / path
    return path


def _redacted_dsn(dsn: str) -> str:
    from yoke_core.domain.yoke_cloud_db_authority import redacted_dsn

    return redacted_dsn(dsn)


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ConnectedEnvError(f"{key} must be a non-empty string")
    return value


def _required_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ConnectedEnvError(f"{key} must be an object")
    return value


def _optional_str(mapping: Mapping[str, Any], key: str) -> Optional[str]:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConnectedEnvError(f"{key} must be a non-empty string when present")
    return value


def _optional_int(mapping: Mapping[str, Any], key: str) -> Optional[int]:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConnectedEnvError(f"{key} must be an integer when present") from exc


def _connection_evidence(connection: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence: dict[str, Any] = {}
    host = _optional_str(connection, "host")
    port = _optional_int(connection, "port")
    if host:
        evidence["host"] = host
    if port is not None:
        evidence["port"] = port
    return evidence


__all__ = [
    "BINDING_RELATIVE_PATH",
    "ConnectedEnv",
    "ConnectedEnvError",
    "ConnectedEnvNotLocalPostgres",
    "PYTEST_ENABLE_ENV",
    "ResolvedDsn",
    "connected_backend",
    "find_binding",
    "load_active",
    "process_env_overrides",
    "resolve_postgres_dsn",
    "sqlite_guard_message",
    "sqlite_guard_reason",
]
