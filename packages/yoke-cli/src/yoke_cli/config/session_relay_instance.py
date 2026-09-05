"""Stable machine-relay instance identity for one configured environment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as machine_schema


PROD_RELAY_LABEL = "com.upyoke.relay"
NON_PROD_RELAY_LABEL_PREFIX = f"{PROD_RELAY_LABEL}."
#: launchd's per-user domain, the one a relay LaunchAgent bootstraps into. It
#: lives beside the labels it qualifies because every caller that addresses a
#: relay service names both together: the local lifecycle target and the Test
#: Mac reset, which reaches the same domain over its own shell.
LAUNCHD_USER_DOMAIN = "gui"
PROD_RELAY_STATE_DIR_NAME = "relay"
#: The service's own streams, in the state dir. The launchd plist points
#: at them and the evidence read serves them back, so the names live once.
RELAY_STDOUT_LOG_NAME = "relay.stdout.log"
RELAY_STDERR_LOG_NAME = "relay.stderr.log"
RELAY_LOG_FILE_NAMES = (RELAY_STDOUT_LOG_NAME, RELAY_STDERR_LOG_NAME)
NON_PROD_RELAY_STATE_ROOT_NAME = "relay-instances"
_INSTANCE_DIGEST_LENGTH = 16


class RelayInstanceError(RuntimeError):
    """The selected connection cannot safely own a relay instance."""


@dataclass(frozen=True)
class RelayInstance:
    """Secret-free identity and storage paths for one relay environment."""

    environment: str
    config_path: Path
    yoke_home: Path
    prod: bool
    label: str
    state_dir: Path

    @property
    def stdout_log(self) -> Path:
        return self.state_dir / RELAY_STDOUT_LOG_NAME

    @property
    def stderr_log(self) -> Path:
        return self.state_dir / RELAY_STDERR_LOG_NAME


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _digest(config_path: Path, environment: str) -> str:
    identity = f"{config_path}\0{environment}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:_INSTANCE_DIGEST_LENGTH]


def prod_https_environments(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return the sole connection class eligible for the legacy prod relay."""
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return ()
    return tuple(
        sorted(
            str(environment)
            for environment, connection in connections.items()
            if isinstance(connection, Mapping)
            and machine_schema.connection_is_prod(connection)
            and str(connection.get("transport") or "").strip()
            == machine_schema.TRANSPORT_HTTPS
        )
    )


def resolve_relay_instance(
    *,
    config_path: str | Path | None = None,
    environment: str | None = None,
    yoke_home: Path | None = None,
) -> RelayInstance:
    """Resolve and validate the exact connection before any lifecycle write."""
    selected_config = _canonical(machine_config.config_path(config_path))
    try:
        payload = machine_config.load_config(selected_config)
        selected_environment = machine_schema.selected_env(
            payload,
            explicit_env=environment,
        )
        issues = [
            issue
            for issue in machine_schema.validate_payload(
                payload,
                explicit_env=selected_environment,
            )
            if issue.severity == "error"
        ]
        if issues:
            raise RelayInstanceError(issues[0].message)
        connection = machine_schema.active_connection(
            payload,
            explicit_env=selected_environment,
        )
    except RelayInstanceError:
        raise
    except Exception as exc:
        raise RelayInstanceError(str(exc)) from exc

    transport = str(connection.get("transport") or "").strip()
    if transport != machine_schema.TRANSPORT_HTTPS:
        raise RelayInstanceError(
            "machine relay requires an https control-plane connection; "
            f"env {selected_environment!r} uses {transport!r}"
        )

    selected_home = _canonical(yoke_home or machine_config.yoke_home())
    is_prod = machine_schema.connection_is_prod(connection)
    if is_prod:
        prod_environments = prod_https_environments(payload)
        if prod_environments != (selected_environment,):
            raise RelayInstanceError(
                "machine relay requires exactly one prod https connection; "
                f"configured prod https envs: {list(prod_environments)}"
            )
        label = PROD_RELAY_LABEL
        state_dir = selected_home / PROD_RELAY_STATE_DIR_NAME
    else:
        instance_digest = _digest(selected_config, selected_environment)
        label = f"{NON_PROD_RELAY_LABEL_PREFIX}{instance_digest}"
        state_dir = selected_home / NON_PROD_RELAY_STATE_ROOT_NAME / instance_digest
    return RelayInstance(
        environment=selected_environment,
        config_path=selected_config,
        yoke_home=selected_home,
        prod=is_prod,
        label=label,
        state_dir=state_dir,
    )


__all__ = [
    "LAUNCHD_USER_DOMAIN",
    "NON_PROD_RELAY_LABEL_PREFIX",
    "NON_PROD_RELAY_STATE_ROOT_NAME",
    "PROD_RELAY_LABEL",
    "PROD_RELAY_STATE_DIR_NAME",
    "RelayInstance",
    "RelayInstanceError",
    "prod_https_environments",
    "resolve_relay_instance",
]
