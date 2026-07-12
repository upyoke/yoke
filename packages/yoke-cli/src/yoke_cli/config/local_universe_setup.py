"""Client-side setup for the machine-local Yoke universe.

``yoke init --local`` births (or verifies) the embedded local universe and
records it in machine config: a ``local`` connection entry (transport
``local-postgres``, DSN stored as a Yoke-owned machine secret file) plus
``active_env=local``. The engine half — binaries, cluster, schema
bootstrap, org card, human actor — is owned by
``yoke_core.domain.local_universe``; this module only orchestrates it and
writes machine-local config. ``yoke universe export`` rides the same lane:
the dump mechanics and DSN-possession authority check are owned by
``yoke_core.domain.universe_export``.

The engine import is dynamic on purpose: the client packages hold no
static import authority over the engine. Local mode is the one lane where
a product install *runs* the engine — activation is explicit, through
this module, never ambient.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, Optional

from yoke_cli.config import machine_config
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config import writer
from yoke_contracts.machine_config import schema as contract

#: The machine-config env label local mode owns.
LOCAL_ENV = "local"
LOCAL_UNIVERSE_CREATE = "create"
LOCAL_UNIVERSE_VERIFY = "verify"
LOCAL_UNIVERSE_UNAVAILABLE = "unavailable"


class LocalUniverseSetupError(RuntimeError):
    """The local universe could not be initialized, exported, or recorded."""


_ENGINE_MISSING_MESSAGE = (
    "the yoke-core engine package is not importable on this machine; "
    "reinstall Yoke (the engine ships in every product install)"
)


def _engine():
    try:
        return importlib.import_module("yoke_core.domain.local_universe")
    except ModuleNotFoundError as exc:
        raise LocalUniverseSetupError(_ENGINE_MISSING_MESSAGE) from exc


def _export_engine():
    try:
        return importlib.import_module("yoke_core.domain.universe_export")
    except ModuleNotFoundError as exc:
        raise LocalUniverseSetupError(_ENGINE_MISSING_MESSAGE) from exc


def run_local_init(
    *,
    org_name: Optional[str] = None,
    force: bool = False,
    config_path: Optional[str] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Birth (or verify) the local universe and point machine config at it.

    Idempotent: a second run detects the live universe, reports, and
    leaves an existing matching ``local`` connection untouched. A socket-only
    DSN relocation reported by the engine is updated automatically because it
    still addresses the same durable cluster. Any other conflicting local
    connection is never clobbered without ``force``.
    """
    engine = _engine()
    try:
        report = dict(engine.birth(org_name=org_name, emit=emit))
    except RuntimeError as exc:  # engine setup errors (binaries, cluster, bootstrap)
        raise LocalUniverseSetupError(str(exc)) from exc
    connection = _ensure_local_connection(
        report["dsn"],
        force=force,
        config_path=config_path,
        equivalent_dsns=tuple(report.get("socket_dsn_aliases") or ()),
    )
    report["connection"] = connection
    if connection["written"] or not _active_env(config_path):
        writer.set_active_env(LOCAL_ENV, path=config_path)
    report["active_env"] = _active_env(config_path)
    report["ok"] = True
    return report


def inspect_local_state(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Describe whether local onboarding will create or reuse a universe."""
    try:
        payload = machine_config.load_config(config_path)
    except machine_config.MachineConfigError as exc:
        return {
            "state": LOCAL_UNIVERSE_UNAVAILABLE,
            "connection": False,
            "active": False,
            "reason": str(exc),
        }
    connections = payload.get("connections")
    entry = connections.get(LOCAL_ENV) if isinstance(connections, dict) else None
    active = str(payload.get("active_env") or "") == LOCAL_ENV
    if not isinstance(entry, dict):
        return {
            "state": LOCAL_UNIVERSE_CREATE,
            "connection": False,
            "active": active,
            "reason": "",
        }
    transport = str(entry.get("transport") or "").strip()
    if transport != contract.DEFAULT_TRANSPORT:
        return {
            "state": LOCAL_UNIVERSE_UNAVAILABLE,
            "connection": True,
            "active": active,
            "reason": (
                f"connections.{LOCAL_ENV}.transport is "
                f"{transport or 'unset'}, not {contract.DEFAULT_TRANSPORT}"
            ),
        }
    if contract.connection_is_prod(entry):
        return {
            "state": LOCAL_UNIVERSE_UNAVAILABLE,
            "connection": True,
            "active": active,
            "reason": f"connections.{LOCAL_ENV} is marked prod",
        }
    if _stored_dsn(entry):
        return {
            "state": LOCAL_UNIVERSE_VERIFY,
            "connection": True,
            "active": active,
            "reason": "",
        }
    return {
        "state": LOCAL_UNIVERSE_UNAVAILABLE,
        "connection": True,
        "active": active,
        "reason": (
            f"connections.{LOCAL_ENV}.credential_source does not point at a "
            "readable DSN secret"
        ),
    }


def postgres_start(emit: Callable[[str], None] = lambda _line: None) -> Dict[str, Any]:
    engine = _engine()
    try:
        return engine.start(emit=emit)
    except RuntimeError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc


def postgres_stop() -> Dict[str, Any]:
    engine = _engine()
    try:
        return engine.stop()
    except RuntimeError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc


def postgres_status() -> Dict[str, Any]:
    engine = _engine()
    try:
        return engine.status()
    except RuntimeError as exc:  # e.g. missing embedded binaries
        raise LocalUniverseSetupError(str(exc)) from exc


def universe_export(
    *,
    out: Optional[str] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Dump the active universe to a portable artifact through the engine.

    The engine owns the whole operation: the DSN-possession authority
    check on the active connection, the directory-vs-file routing of
    ``out`` (a trailing path separator means a directory, so the raw
    string passes through untouched), the org-slug/timestamp default
    filename, and the ``pg_dump`` custom-format invocation.
    """
    engine = _export_engine()
    try:
        return dict(engine.export_universe(out=out or None, emit=emit))
    except RuntimeError as exc:  # authority refusal, dead server, dump failure
        raise LocalUniverseSetupError(str(exc)) from exc


def _ensure_local_connection(
    dsn: str,
    *,
    force: bool,
    config_path: Optional[str],
    equivalent_dsns: tuple[str, ...] = (),
) -> Dict[str, Any]:
    """Record the local DSN under ``connections.local`` without clobbering."""
    payload = machine_config.load_config(config_path)
    connections = payload.get("connections")
    entry = connections.get(LOCAL_ENV) if isinstance(connections, dict) else None
    if isinstance(entry, dict):
        transport = str(entry.get("transport") or "").strip()
        existing_dsn = _stored_dsn(entry)
        if transport == contract.DEFAULT_TRANSPORT and existing_dsn == dsn:
            return {"env": LOCAL_ENV, "connection": dict(entry), "written": False}
        same_cluster_relocation = (
            transport == contract.DEFAULT_TRANSPORT
            and not contract.connection_is_prod(entry)
            and existing_dsn in equivalent_dsns
        )
        if not force and not same_cluster_relocation:
            raise LocalUniverseSetupError(
                f"machine config already has a {LOCAL_ENV!r} connection that "
                f"does not match the local universe (transport "
                f"{transport or 'unset'!s}); rerun with --force to replace it"
            )
    try:
        # replace=True: a conflicting entry being overwritten under --force
        # must not leak stray keys (e.g. an https entry's api_url) into the
        # rewritten local connection.
        result = writer.set_connection(
            LOCAL_ENV,
            transport=contract.DEFAULT_TRANSPORT,
            dsn=dsn,
            prod=False,
            replace=True,
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc
    result["written"] = True
    return result


def _stored_dsn(entry: Dict[str, Any]) -> Optional[str]:
    source = entry.get("credential_source")
    if not isinstance(source, dict):
        return None
    if source.get("kind") != contract.CREDENTIAL_KIND_DSN_FILE:
        return None
    dsn_path = source.get("path")
    if not dsn_path:
        return None
    try:
        return machine_secrets.read_secret_file(dsn_path, "DSN")
    except machine_secrets.MachineSecretError:
        return None


def _active_env(config_path: Optional[str]) -> str:
    return str(machine_config.load_config(config_path).get("active_env") or "")


__all__ = [
    "LOCAL_ENV",
    "LOCAL_UNIVERSE_CREATE",
    "LOCAL_UNIVERSE_UNAVAILABLE",
    "LOCAL_UNIVERSE_VERIFY",
    "LocalUniverseSetupError",
    "inspect_local_state",
    "postgres_start",
    "postgres_status",
    "postgres_stop",
    "run_local_init",
    "universe_export",
]
