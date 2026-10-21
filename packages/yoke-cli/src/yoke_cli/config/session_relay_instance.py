"""Stable machine-relay instance identity for one configured environment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as machine_schema


RELAY_LOGOUT_BEHAVIOR = (
    "The relay stops after the last login session logs out; linger is disabled."
)

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
#: How a relay names the directory tree it owns to the processes it starts.
#: The relay's runtime entrypoint exports it beside the Python activation
#: state it sets, so a process handing off to a foreign CLI drops exactly
#: what the relay owns instead of inferring that root from the shape of a
#: release path. A relay that exports no activation state exports no root.
RELAY_STATE_DIR_ENV = "YOKE_RELAY_STATE_DIR"
#: What the relay exports so its own imports resolve to the release it
#: selected. A relay-internal Python process needs them; a foreign CLI it
#: starts must not have them, or that CLI's project tooling (`uv run
#: --active` is the observed case) treats the relay's release as the
#: environment of the project it is working in, and the installed `yoke`
#: reports the relay's release as its own version.
_RELAY_PYTHON_ACTIVATION_ENV = ("VIRTUAL_ENV", "PYTHONPATH")
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
    #: Whether this relay tracks the build its control plane serves. An https
    #: plane serves a release the relay must fetch and pin; a local universe is
    #: served by the same machine the relay runs on, so the installed Yoke is
    #: already the served build and there is nothing to follow.
    follows_served_release: bool = True
    #: Whether this relay's environment is the machine config's ``active_env``.
    #: Exactly one relay per machine can be, so it alone moves the installed
    #: CLI to the release its plane serves.
    machine_active: bool = False

    @property
    def stdout_log(self) -> Path:
        return self.state_dir / RELAY_STDOUT_LOG_NAME

    @property
    def stderr_log(self) -> Path:
        return self.state_dir / RELAY_STDERR_LOG_NAME


def _without_relay_owned_path_entries(path_value: str, state_dir: str) -> str:
    """Drop the search-path entries that live inside the relay's own tree.

    The relay puts its launch link's ``bin`` ahead of the machine's own
    directories so launchd can find it, and that directory holds a
    ``python`` as well as a ``yoke``. Entries outside the relay's tree are
    the user's and stay, including whichever installed launcher the machine
    already resolves ``yoke`` through.
    """
    owned = Path(state_dir)
    kept = [
        entry
        for entry in path_value.split(os.pathsep)
        if not (
            entry and Path(entry).is_absolute() and Path(entry).is_relative_to(owned)
        )
    ]
    return os.pathsep.join(kept)


def strip_relay_owned_python_state(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return ``env`` with nothing of the relay's own Python left in it.

    Call this at the boundary where a relay-internal process starts an
    actual foreign CLI binary — and only there. The relay's supervisor and
    its detached workers start on the stable runtime interpreter, which has
    no packages of its own and imports itself through exactly the
    activation state this drops; stripping it before one of those starts
    breaks the process rather than the leak.

    The relay names the tree it owns rather than leaving it to be inferred:
    the activation variables always go, and the search path is filtered
    only when the relay declared its own root. That declaration is dropped
    too, so a worker never reads it as an invitation to write there.
    """
    result = dict(os.environ if env is None else env)
    for name in _RELAY_PYTHON_ACTIVATION_ENV:
        result.pop(name, None)
    state_dir = result.pop(RELAY_STATE_DIR_ENV, "").strip()
    search_path = result.get("PATH", "")
    if state_dir and search_path:
        result["PATH"] = _without_relay_owned_path_entries(search_path, state_dir)
    return result


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _digest(config_path: Path, environment: str) -> str:
    identity = f"{config_path}\0{environment}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:_INSTANCE_DIGEST_LENGTH]


def relay_instance_label(
    *, config_path: str | Path, environment: str, prod: bool
) -> str:
    """The service name shared by setup preview and the validated installer."""
    if prod:
        return PROD_RELAY_LABEL
    return f"{NON_PROD_RELAY_LABEL_PREFIX}{_digest(_canonical(Path(config_path)), environment)}"


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


def door_relay_refusal(instance: RelayInstance) -> str:
    """Why a relay must not be installed or served on *instance*, or ``""``.

    A paired ``*-db-admin`` door's https env serves the same universe, and a
    door refuses routine calls (``use_https_env``), relay claims included.
    Status and uninstall stay available so an earlier relay can be moved.
    """
    try:
        payload = machine_config.load_config(instance.config_path)
    except Exception:  # noqa: BLE001 - resolution already validated the config
        return ""
    served = machine_schema.same_universe_https_env(payload, instance.environment)
    if not served:
        return ""
    return (
        f"use_https_env: env {instance.environment!r} is a direct database door "
        f"for the universe {served!r} serves, so its relay runs there. Move "
        f"it: `yoke --env {instance.environment} relay uninstall`, then "
        f"`yoke --env {served} relay install`"
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
    is_prod = machine_schema.connection_is_prod(connection)
    follows_served_release = transport == machine_schema.TRANSPORT_HTTPS
    if not follows_served_release:
        if transport not in machine_schema.POSTGRES_TRANSPORTS:
            raise RelayInstanceError(
                "machine relay requires an https or local-postgres control-plane "
                f"connection; env {selected_environment!r} uses {transport!r}"
            )
        if is_prod:
            # A prod-flagged local-postgres connection is direct database
            # authority into a universe an https connection already serves, so
            # its relay belongs to that connection. Standing one up here would
            # poll one universe from two relays on one machine.
            raise RelayInstanceError(
                "machine relay refuses a prod local-postgres connection; env "
                f"{selected_environment!r} is direct database authority for a "
                "hosted universe, whose relay runs on its https connection"
            )

    selected_home = _canonical(yoke_home or machine_config.yoke_home())
    if is_prod:
        prod_environments = prod_https_environments(payload)
        if prod_environments != (selected_environment,):
            raise RelayInstanceError(
                "machine relay requires exactly one prod https connection; "
                f"configured prod https envs: {list(prod_environments)}"
            )
        state_dir = selected_home / PROD_RELAY_STATE_DIR_NAME
    else:
        instance_digest = _digest(selected_config, selected_environment)
        state_dir = selected_home / NON_PROD_RELAY_STATE_ROOT_NAME / instance_digest
    return RelayInstance(
        environment=selected_environment,
        config_path=selected_config,
        yoke_home=selected_home,
        prod=is_prod,
        label=relay_instance_label(
            config_path=selected_config, environment=selected_environment, prod=is_prod
        ),
        state_dir=state_dir,
        follows_served_release=follows_served_release,
        machine_active=(
            selected_environment == machine_schema.configured_active_env(payload)
        ),
    )


__all__ = [
    "LAUNCHD_USER_DOMAIN",
    "NON_PROD_RELAY_LABEL_PREFIX",
    "NON_PROD_RELAY_STATE_ROOT_NAME",
    "PROD_RELAY_LABEL",
    "PROD_RELAY_STATE_DIR_NAME",
    "RELAY_STATE_DIR_ENV",
    "RELAY_LOGOUT_BEHAVIOR",
    "RelayInstance",
    "door_relay_refusal",
    "RelayInstanceError",
    "prod_https_environments",
    "resolve_relay_instance",
    "relay_instance_label",
    "strip_relay_owned_python_state",
]
