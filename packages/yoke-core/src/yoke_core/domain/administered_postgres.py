"""Identify Postgres targets that this machine administers but does not own.

The selected connection is provenance, not target identity. A caller can name
the same cluster through ``YOKE_PG_DSN``, a DSN file, a context binding, or a
live connection after selection has changed. Safety decisions therefore
compare the target's normalized host/port endpoint with every prod-flagged
local-Postgres connection registered on the machine.

Endpoint identity is deliberately database-agnostic: ``postgres``, the Yoke
control-plane database, a validation copy, and a test database all live on the
same administered cluster. Credentials are retained only when a Doctor check
needs a read connection and are excluded from object representations.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import (
    CREDENTIAL_KIND_DSN_FILE,
    CREDENTIAL_KIND_ENV,
    POSTGRES_TRANSPORTS,
    connection_is_prod,
)

DEFAULT_POSTGRES_PORT = "5432"
ADMINISTERED_TARGETS_ENV = "YOKE_ADMINISTERED_POSTGRES_TARGETS"

ClusterEndpoint = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class AdministeredPostgresTarget:
    """One configured administered cluster and its usable local credential."""

    env: str
    endpoint: ClusterEndpoint | None
    dsn: str | None = field(default=None, repr=False)


def configured_administered_targets() -> tuple[AdministeredPostgresTarget, ...]:
    """Return every prod-flagged local-Postgres target this machine knows."""

    targets = {
        target.env: target
        for target in _inventory_targets(os.environ.get(ADMINISTERED_TARGETS_ENV))
    }
    try:
        payload = machine_config_runtime.load_config()
        config_dir = machine_config_runtime.config_path().parent
    except Exception:  # noqa: BLE001 - unrelated config errors surface elsewhere
        return tuple(targets[env] for env in sorted(targets))
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return tuple(targets[env] for env in sorted(targets))
    for raw_env, raw_connection in sorted(
        connections.items(), key=lambda row: str(row[0])
    ):
        if not isinstance(raw_connection, Mapping):
            continue
        transport = str(raw_connection.get("transport") or "").strip()
        if transport not in POSTGRES_TRANSPORTS or not connection_is_prod(
            raw_connection
        ):
            continue
        dsn = _credential_dsn(raw_connection, config_dir=config_dir)
        endpoint = endpoint_from_dsn(dsn) if dsn else None
        if endpoint is None:
            endpoint = _declared_endpoint(raw_connection)
        env = str(raw_env)
        targets[env] = AdministeredPostgresTarget(
            env=env,
            endpoint=endpoint,
            dsn=dsn,
        )
    return tuple(targets[env] for env in sorted(targets))


def environment_with_administered_target_inventory(
    env: Mapping[str, str],
) -> dict[str, str]:
    """Preserve endpoint identity when a child must not read machine config."""

    resolved = dict(env)
    targets = {
        target.env: target
        for target in _inventory_targets(resolved.get(ADMINISTERED_TARGETS_ENV))
    }
    targets.update(
        (target.env, target)
        for target in configured_administered_targets()
        if target.endpoint is not None
    )
    inventory = {
        name: target.endpoint
        for name, target in sorted(targets.items())
        if target.endpoint is not None
    }
    if inventory:
        resolved[ADMINISTERED_TARGETS_ENV] = json.dumps(
            inventory,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        resolved.pop(ADMINISTERED_TARGETS_ENV, None)
    return resolved


def administering_target(
    *,
    dsn: str | None = None,
    connection: Any = None,
) -> str:
    """Return the administering env for the concrete target, or ``""``.

    A resolved endpoint wins over ambient selection. The selection is only a
    fallback when the caller has no inspectable target yet, preserving the
    fail-closed guard before a connection exists without misclassifying an
    explicit test-cluster DSN selected from an administering shell.
    """

    if dsn is not None and connection is not None:
        raise ValueError("pass a DSN or a connection, not both")
    endpoint = (
        endpoint_from_dsn(dsn)
        if dsn is not None
        else endpoint_from_connection(connection)
    )
    if endpoint is not None:
        for target in configured_administered_targets():
            if target.endpoint == endpoint:
                return target.env
        return ""
    return selected_administering_env()


def selected_administering_env() -> str:
    """Return the selected prod local-Postgres env when it names the target."""

    try:
        env = machine_config_runtime.active_env()
        connection = machine_config_runtime.active_connection()
    except Exception:  # noqa: BLE001 - config problems surface at their owner
        return ""
    transport = str(connection.get("transport") or "").strip()
    if transport not in POSTGRES_TRANSPORTS or not connection_is_prod(connection):
        return ""
    return env


def endpoint_from_dsn(dsn: str | None) -> ClusterEndpoint | None:
    """Normalize a libpq DSN to the host/port cluster endpoint it reaches."""

    if not str(dsn or "").strip():
        return None
    try:
        from psycopg.conninfo import conninfo_to_dict

        parameters = conninfo_to_dict(str(dsn))
    except Exception:  # noqa: BLE001 - malformed DSNs fail at connection time
        return None
    return _endpoint_from_parameters(parameters)


def endpoint_from_connection(connection: Any) -> ClusterEndpoint | None:
    """Read the resolved endpoint from a live psycopg connection, if present."""

    info = getattr(connection, "info", None)
    parameters = getattr(info, "dsn_parameters", None)
    if isinstance(parameters, Mapping):
        endpoint = _endpoint_from_parameters(parameters)
        if endpoint is not None:
            return endpoint
    host = getattr(info, "host", None)
    port = getattr(info, "port", None)
    return _endpoint_from_parameters({"host": host, "port": port})


def _credential_dsn(connection: Mapping[str, Any], *, config_dir: Path) -> str | None:
    source = connection.get("credential_source")
    if not isinstance(source, Mapping):
        return None
    kind = str(source.get("kind") or "")
    if kind == CREDENTIAL_KIND_DSN_FILE:
        raw_path = str(source.get("path") or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = config_dir / path
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    if kind == CREDENTIAL_KIND_ENV:
        name = str(source.get("name") or "").strip()
        if not name:
            return None
        return os.environ.get(name, "").strip() or None
    return None


def _declared_endpoint(connection: Mapping[str, Any]) -> ClusterEndpoint | None:
    postgres = connection.get("postgres")
    return (
        _endpoint_from_parameters(postgres) if isinstance(postgres, Mapping) else None
    )


def _inventory_targets(raw: str | None) -> tuple[AdministeredPostgresTarget, ...]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    targets: list[AdministeredPostgresTarget] = []
    for raw_env, raw_endpoint in payload.items():
        if not isinstance(raw_endpoint, list):
            continue
        pairs: list[tuple[str, str]] = []
        for pair in raw_endpoint:
            if not isinstance(pair, list) or len(pair) != 2:
                pairs = []
                break
            host, port = (str(value).strip() for value in pair)
            if not host or not port:
                pairs = []
                break
            pairs.append((host, port))
        if pairs:
            targets.append(
                AdministeredPostgresTarget(
                    env=str(raw_env),
                    endpoint=tuple(sorted(pairs)),
                )
            )
    return tuple(targets)


def _endpoint_from_parameters(parameters: Mapping[str, Any]) -> ClusterEndpoint | None:
    raw_hosts = parameters.get("hostaddr") or parameters.get("host")
    if not str(raw_hosts or "").strip():
        return None
    hosts = [part.strip() for part in str(raw_hosts).split(",")]
    raw_ports = str(parameters.get("port") or DEFAULT_POSTGRES_PORT)
    ports = [part.strip() for part in raw_ports.split(",")]
    if len(ports) == 1 and len(hosts) > 1:
        ports *= len(hosts)
    if len(hosts) != len(ports) or any(
        not host or not port for host, port in zip(hosts, ports)
    ):
        return None
    return tuple(
        sorted((_normalize_host(host), port) for host, port in zip(hosts, ports))
    )


def _normalize_host(host: str) -> str:
    value = host.strip().strip("[]")
    if value.lower() == "localhost":
        return "loopback"
    try:
        if ipaddress.ip_address(value).is_loopback:
            return "loopback"
    except ValueError:
        pass
    if value.startswith("/"):
        return str(Path(value).expanduser())
    return value.lower().rstrip(".")


__all__ = [
    "ADMINISTERED_TARGETS_ENV",
    "AdministeredPostgresTarget",
    "administering_target",
    "configured_administered_targets",
    "environment_with_administered_target_inventory",
    "endpoint_from_connection",
    "endpoint_from_dsn",
    "selected_administering_env",
]
