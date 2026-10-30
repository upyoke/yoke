"""Client-side setup for the machine-local Yoke universe.

``yoke init --local`` births (or verifies) the embedded local universe and
records it in machine config: a ``local`` connection entry (transport
``local-postgres``, DSN stored as a Yoke-owned machine secret file) plus
``active_env=local`` only when no connection is active or activation is requested.
The engine half — binaries, cluster, schema bootstrap, org card, human actor —
is owned by
``yoke_core.domain.local_universe``; this module only orchestrates it and
writes machine-local config. ``yoke universe export`` rides the same lane:
the dump mechanics and DSN-possession authority check are owned by
``yoke_core.domain.universe_export``.

The engine imports are dynamic on purpose: the client packages hold no
static import authority over the engine. Local mode is the one lane where
a product install *runs* the engine — activation is explicit, through
this module, never ambient.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from yoke_cli.config import machine_config
from yoke_cli.config import machine_config_file
from yoke_cli.config import writer
from yoke_cli.config.local_universe_connection import (
    LOCAL_ENV,
    LocalUniverseSetupError,
    ensure_local_connection,
    stored_dsn,
)
from yoke_contracts.control_plane_locality import RemoteControlPlaneConnectionError
from yoke_contracts.machine_config import schema as contract

LOCAL_UNIVERSE_CREATE = "create"
LOCAL_UNIVERSE_VERIFY = "verify"
LOCAL_UNIVERSE_UNAVAILABLE = "unavailable"


#: What every client-side engine seam says when the engine half of the
#: install is missing. Shared, because a product install that lost its
#: engine gives the same answer whichever seam noticed first.
ENGINE_MISSING_MESSAGE = (
    "the yoke-core engine package is not importable on this machine; "
    "reinstall Yoke (the engine ships in every product install)"
)


def _engine():
    try:
        return importlib.import_module("yoke_core.domain.local_universe")
    except ModuleNotFoundError as exc:
        raise LocalUniverseSetupError(ENGINE_MISSING_MESSAGE) from exc


def _export_engine():
    try:
        return importlib.import_module("yoke_core.domain.universe_export")
    except ModuleNotFoundError as exc:
        raise LocalUniverseSetupError(ENGINE_MISSING_MESSAGE) from exc


def _import_engine():
    try:
        return importlib.import_module("yoke_core.domain.local_universe_import")
    except ModuleNotFoundError as exc:
        raise LocalUniverseSetupError(ENGINE_MISSING_MESSAGE) from exc


def run_local_init(
    *,
    org_name: Optional[str] = None,
    admin_name: Optional[str] = None,
    force: bool = False,
    activate: bool = False,
    config_path: Optional[str] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Birth (or verify) the local universe and point machine config at it.

    Idempotent: a second run detects the live universe, reports, and
    leaves an existing matching ``local`` connection untouched. A socket-only
    DSN relocation reported by the engine is updated automatically because it
    still addresses the same durable cluster. Missing credential files and stale
    actor bindings are repaired automatically. Other conflicting connections
    require ``force``; activation is independent. ``admin_name`` is the
    installer's name; a new universe's first admin is created as that person,
    and creating one without it refuses by name.
    """
    try:
        machine_config_file.ensure_owner_only_directory(machine_config.yoke_home())
    except machine_config_file.MachineConfigFileError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc
    engine = _engine()
    try:
        report = dict(engine.birth(org_name=org_name, admin_name=admin_name, emit=emit))
    except RemoteControlPlaneConnectionError as exc:
        # BaseException: a leftover ambient connect would traceback past
        # RuntimeError. Named setup error plus retry is the product recovery.
        raise LocalUniverseSetupError(
            f"{exc} Retry `yoke init --local`; it opens the owned local "
            "cluster without using the active remote connection."
        ) from exc
    except RuntimeError as exc:  # binaries, cluster, bootstrap
        raise LocalUniverseSetupError(str(exc)) from exc
    binding = _inspect_operating_actor(report["dsn"], config_path)
    connection = ensure_local_connection(
        report["dsn"],
        force=force,
        config_path=config_path,
        equivalent_dsns=tuple(report.get("socket_dsn_aliases") or ()),
        actor_universe_mismatch=binding == "SESSION_ACTOR_UNIVERSE_MISMATCH",
    )
    report["connection"] = connection
    if activate or not _active_env(config_path):
        writer.set_active_env(LOCAL_ENV, path=config_path)
    _record_operating_actor(report, config_path)
    report["operating_actor_repaired"] = bool(binding)
    repairs = list(connection.get("repairs") or ())
    if binding and not any("operating actor" in reason for reason in repairs):
        repairs.append("stale operating actor binding")
    for reason in repairs:
        emit(f"  [local-universe] repaired connections.local: {reason}")
    report["active_env"] = _active_env(config_path)
    report["ok"] = True
    return report


def _inspect_operating_actor(dsn, config_path):
    payload = machine_config.load_config(config_path)
    entry = (payload.get("connections") or {}).get(LOCAL_ENV) or {}
    if not entry.get("operating_actor"):
        return ""
    binding = importlib.import_module("yoke_core.domain.local_universe_operating_actor")
    try:
        return binding.inspect_operating_actor(dsn=dsn, config_path=config_path)
    except Exception as exc:
        raise LocalUniverseSetupError(
            "local_actor_inspection_failed: could not verify the owned local "
            "universe; retry `yoke init --local` after checking local Postgres"
        ) from exc


def _record_operating_actor(report, config_path):
    """Bind the actor birth returned after its local connection is configured."""
    binding = importlib.import_module("yoke_core.domain.local_universe_operating_actor")
    try:
        binding.record_operating_actor(
            report["human_actor_id"],
            dsn=report["dsn"],
            env=LOCAL_ENV,
            config_path=config_path,
        )
    except Exception as exc:
        raise LocalUniverseSetupError(
            f"local_actor_binding_failed: {exc}; retry `yoke init --local` "
            "to record the operating actor before starting a session"
        ) from exc


def _unsupported_host_reason() -> str:
    """The engine's refusal for this host, or "" when local mode can run here."""
    try:
        return _engine().unsupported_host_reason()
    except LocalUniverseSetupError as exc:
        return str(exc)


def inspect_local_state(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Describe whether local onboarding will create or reuse a universe."""
    host_reason = _unsupported_host_reason()
    if host_reason:
        return {
            "state": LOCAL_UNIVERSE_UNAVAILABLE,
            "connection": False,
            "active": False,
            "host_unsupported": True,
            "reason": host_reason,
        }
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
    if contract.connection_is_protected(entry):
        return {
            "state": LOCAL_UNIVERSE_UNAVAILABLE,
            "connection": True,
            "active": active,
            "reason": f"connections.{LOCAL_ENV} is marked protected",
        }
    source = entry.get("credential_source") or {}
    if stored_dsn(entry) or (
        source.get("kind") == contract.CREDENTIAL_KIND_DSN_FILE
        and source.get("path")
        and not Path(source["path"]).expanduser().exists()
    ):
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


def local_cluster_initialized() -> bool:
    """Whether this machine holds embedded Postgres data, without starting it."""
    engine = _engine()
    return (engine.cluster_spec().data_dir / "PG_VERSION").is_file()


def _refuse_test_cluster_override() -> None:
    import os

    root = os.environ.get("YOKE_PG_CLUSTER_ROOT")
    if root is not None:
        raise LocalUniverseSetupError(
            f"local_postgres_test_cluster_override: YOKE_PG_CLUSTER_ROOT={root}; "
            "use yoke_core.tools.pg_testcluster start/stop for that test cluster, "
            "or unset YOKE_PG_CLUSTER_ROOT to operate the local universe"
        )


def postgres_start(emit: Callable[[str], None] = lambda _line: None) -> Dict[str, Any]:
    _refuse_test_cluster_override()
    engine = _engine()
    try:
        return engine.start(emit=emit)
    except RuntimeError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc


def postgres_stop() -> Dict[str, Any]:
    _refuse_test_cluster_override()
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
    exclude_artifacts: bool = False,
    estimate: bool = False,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Export the active universe to one portable archive via the engine.

    The engine owns the whole operation: the DSN-possession authority
    check on the active connection, the directory-vs-file routing of
    ``out`` (a trailing path separator means a directory, so the raw
    string passes through untouched), the org-slug/timestamp default
    filename, the snapshot-bound ``pg_dump`` invocation, and packing the
    dump plus its freeze receipt into one tar artifact.
    """
    engine = _export_engine()
    try:
        if estimate:
            transfer = importlib.import_module(
                "yoke_core.domain.universe_artifact_transfer"
            )
            return dict(transfer.estimate_universe(exclude_artifacts=exclude_artifacts))
        options = {"exclude_artifacts": True} if exclude_artifacts else {}
        return dict(engine.export_universe(out=out or None, emit=emit, **options))
    except RuntimeError as exc:  # authority refusal, dead server, dump failure
        raise LocalUniverseSetupError(str(exc)) from exc


def universe_import(*, archive: str) -> Dict[str, Any]:
    """Replace the active local universe from one portable archive."""
    engine = _import_engine()
    try:
        return dict(engine.import_universe(archive))
    except RuntimeError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc


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
    "universe_import",
    "universe_export",
]
