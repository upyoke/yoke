"""The machine-local Yoke universe: an embedded Postgres control plane.

Local mode keeps all state on the machine: one embedded Postgres cluster
under ``~/.yoke/local-universe/`` (unix-socket-only, trust auth on the
socket, binaries from :mod:`yoke_core.domain.postgres_binaries`), carrying
the same control-plane schema every other deployment mode runs. No signup,
no server, no human credentials — the engine stores none anywhere, and in
local mode the DSN never leaves the machine.

Three surfaces:

* Cluster lifecycle — :func:`start`, :func:`stop`, :func:`status` manage
  the embedded server idempotently.
* :func:`birth` — one-shot creation of a fresh universe: engine binaries
  fetched lazily, cluster started, schema bootstrapped through
  :mod:`yoke_core.domain.environment_bootstrap`, sentinels verified, the
  single-row org identity card ensured, and the one auto-created human
  actor guaranteed (labeled with the OS login). Re-running against a live
  universe verifies the sentinel tables and repairs a half-born universe
  by re-running the idempotent init chain instead of re-birthing.
* :func:`local_dsn` — the connection string the machine config records;
  possession of it is the only access control local mode needs.
"""

from __future__ import annotations

import contextlib
import getpass
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_core.domain import postgres_binaries
from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

#: Directory under the machine runtime dir holding the universe cluster
#: (``data/``, ``sock/``, ``server.log``).
LOCAL_UNIVERSE_DIR_NAME = "local-universe"

#: Cluster superuser and control-plane database name. Trust auth on the
#: private unix socket makes filesystem ownership the access boundary,
#: so no password exists to manage.
LOCAL_SUPERUSER = "yoke"
LOCAL_DBNAME = "yoke"


class LocalUniverseError(RuntimeError):
    """The embedded local universe could not be started or created."""


def universe_root() -> Path:
    return machine_runtime.yoke_home() / LOCAL_UNIVERSE_DIR_NAME


def cluster_spec(
    root: Optional[Path] = None, bin_dir: Optional[Path] = None,
) -> ClusterSpec:
    """The durable local-universe cluster description.

    No throwaway-cluster tuning: durability settings stay at Postgres
    defaults because this cluster IS the user's authoritative state.
    """
    return ClusterSpec(
        root=root if root is not None else universe_root(),
        superuser=LOCAL_SUPERUSER,
        bin_dir=bin_dir,
        stop_mode="fast",
    )


def ensure_engine_binaries(
    emit: Callable[[str], None] = lambda _line: None,
) -> Path:
    """Resolve the embedded engine binaries, fetching on first use."""
    return postgres_binaries.ensure_binaries(emit=emit)


def local_dsn(spec: Optional[ClusterSpec] = None) -> str:
    return postgres_cluster.dsn(_spec_or_default(spec), dbname=LOCAL_DBNAME)


def start(
    spec: Optional[ClusterSpec] = None,
    *,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Idempotently start the embedded cluster; returns a status payload."""
    resolved = _resolve_spec(spec, emit=emit)
    rc = postgres_cluster.ensure_started(resolved)
    if rc != 0:
        raise LocalUniverseError(
            f"embedded Postgres failed to start (exit {rc}); see "
            f"{resolved.log_file}"
        )
    ensure_database(resolved)
    return status(resolved)


def stop(spec: Optional[ClusterSpec] = None) -> Dict[str, Any]:
    resolved = _spec_or_default(spec)
    try:
        rc = postgres_cluster.stop(resolved)
    except FileNotFoundError as exc:
        raise _missing_binaries_error(exc) from exc
    if rc != 0:
        raise LocalUniverseError(f"embedded Postgres failed to stop (exit {rc})")
    return status(resolved)


def status(spec: Optional[ClusterSpec] = None) -> Dict[str, Any]:
    resolved = _spec_or_default(spec)
    try:
        running = postgres_cluster.is_ready(resolved)
    except FileNotFoundError as exc:
        raise _missing_binaries_error(exc) from exc
    payload: Dict[str, Any] = {
        "root": str(resolved.root),
        "initialized": (resolved.data_dir / "PG_VERSION").exists(),
        "running": running,
        "binaries": str(postgres_binaries.installed_bin_dir() or ""),
    }
    if running:
        payload["dsn"] = local_dsn(resolved)
    return payload


def ensure_database(
    spec: ClusterSpec, dbname: str = LOCAL_DBNAME,
) -> None:
    """Create the control-plane database once (initdb only makes postgres)."""
    probe = postgres_cluster.psql(
        spec, f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'",
    )
    if probe.returncode != 0:
        raise LocalUniverseError(
            f"database probe failed: {probe.stderr.strip() or probe.stdout.strip()}"
        )
    if probe.stdout.strip() == "1":
        return
    created = postgres_cluster.psql(spec, f'CREATE DATABASE "{dbname}"')
    if created.returncode != 0:
        raise LocalUniverseError(
            f"CREATE DATABASE {dbname} failed: "
            f"{created.stderr.strip() or created.stdout.strip()}"
        )


def is_born(spec: Optional[ClusterSpec] = None) -> bool:
    """True when the universe DB already carries a bootstrapped org card.

    Cluster-spec adapter over the shared DSN-level probe
    :func:`yoke_core.domain.environment_bootstrap.universe_is_born`.
    """
    from yoke_core.domain import environment_bootstrap

    return environment_bootstrap.universe_is_born(
        local_dsn(_spec_or_default(spec))
    )


def birth(
    *,
    org_name: Optional[str] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Create, verify, or repair the local universe end to end.

    Returns a payload carrying ``born`` (False when the universe was
    already live), ``repaired`` (True when a live universe failed
    sentinel verification and the idempotent init chain was re-run),
    ``verified`` (the sentinel counts proving the control plane is
    complete), the cluster status, and the DSN the machine config
    should record.
    """
    bin_dir = ensure_engine_binaries(emit)
    spec = cluster_spec(bin_dir=bin_dir)
    emit(f"  [local-universe] starting embedded Postgres at {spec.root}")
    cluster = start(spec, emit=emit)
    dsn = local_dsn(spec)
    already_live = is_born(spec)
    report: Dict[str, Any] = {
        "born": not already_live,
        "repaired": False,
        "cluster": cluster,
        "dsn": dsn,
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(pinned_authority(dsn))
        login = _os_login_label()
        if login:
            from yoke_core.domain.actors import LOCAL_HUMAN_LABEL_ENV

            # The init chain invokes its modules with no parameters, so the
            # universe owner's label rides the same pinned-env idiom as the
            # DSN authority; canonical-actor seeding consumes it.
            stack.enter_context(_pinned_env(LOCAL_HUMAN_LABEL_ENV, login))
        if already_live:
            emit("  [local-universe] universe already live; verifying")
            report["verified"], report["repaired"] = _verify_or_repair(emit)
        else:
            from yoke_core.domain import environment_bootstrap

            emit("  [local-universe] bootstrapping control-plane schema")
            report["verified"] = environment_bootstrap.run_bootstrap(emit=emit)
        report["org"] = _ensure_org_card(org_name, emit)
        report["human_actor_id"] = _ensure_human_actor(emit)
    return report


def _verify_or_repair(
    emit: Callable[[str], None],
) -> tuple[Dict[str, int], bool]:
    """Verify a live universe's sentinel tables, repairing on failure.

    :func:`is_born` is only a liveness probe (the org card exists), so a
    first-run crash partway through the init chain leaves a half-born
    universe it cannot distinguish from a complete one. Sentinel
    verification is the truth check; on failure the idempotent init
    chain is re-run (safe and cheap) and verification repeats. Returns
    ``(sentinel_counts, repaired)``.
    """
    from yoke_core.domain import environment_bootstrap

    try:
        return environment_bootstrap.verify_bootstrap(emit), False
    except environment_bootstrap.BootstrapError as exc:
        emit(f"  [local-universe] verification failed: {exc}")
        emit("  [local-universe] repairing: re-running the idempotent bootstrap")
        return environment_bootstrap.run_bootstrap(emit=emit), True


@contextlib.contextmanager
def pinned_authority(dsn: str) -> Iterator[None]:
    """Pin the ambient Postgres authority to the local universe."""
    from yoke_core.domain import db_backend

    with _pinned_env(db_backend.PG_DSN_ENV, dsn):
        yield


@contextlib.contextmanager
def _pinned_env(name: str, value: str) -> Iterator[None]:
    """Set one env var for the duration of the block, then restore it."""
    prior = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior


def _os_login_label() -> Optional[str]:
    """The OS login that labels a fresh universe's human actor, or None."""
    try:
        return getpass.getuser() or None
    except Exception:
        return None


def _ensure_org_card(
    org_name: Optional[str], emit: Callable[[str], None],
) -> Dict[str, Any]:
    """Ensure the single-row org identity card, applying a requested name."""
    from yoke_core.domain import db_helpers, org_schema

    conn = db_helpers.connect()
    try:
        card = org_schema.ensure_org_identity_card(conn, org_name)
        if org_name:
            emit(f"  [local-universe] org identity card named {org_name!r}")
        return dict(card)
    finally:
        conn.close()


def _ensure_human_actor(emit: Callable[[str], None]) -> int:
    """Return the universe's one human actor id, seeding as a backstop.

    The bootstrap init chain normally seeds the human actor (labeled
    from the pinned OS-login injection), so on the birth path this is a
    lookup. The seeding branch is a backstop for a universe whose
    bootstrap predates canonical-actor seeding. No user records exist —
    the actor row is the whole identity.
    """
    from yoke_core.domain import actors, db_helpers

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is not None:
            return int(row[0])
        actor_id = actors.seed_human_actor(conn)
        actors.set_actor_label(
            conn, actor_id, _os_login_label() or actors.DEFAULT_LOCAL_HUMAN_LABEL,
        )
        emit(f"  [local-universe] seeded local human actor {actor_id}")
        return actor_id
    finally:
        conn.close()


def _missing_binaries_error(exc: FileNotFoundError) -> LocalUniverseError:
    return LocalUniverseError(
        "embedded Postgres binaries are missing: expected "
        f"{postgres_binaries.version_dir() / 'bin'} and found no Postgres "
        f"tools on PATH ({exc}). Run `yoke local-postgres start` (or "
        "`yoke init --local`) to refetch the embedded engine."
    )


def _spec_or_default(spec: Optional[ClusterSpec]) -> ClusterSpec:
    if spec is not None:
        return spec
    return cluster_spec(bin_dir=postgres_binaries.installed_bin_dir())


def _resolve_spec(
    spec: Optional[ClusterSpec], *, emit: Callable[[str], None],
) -> ClusterSpec:
    if spec is not None:
        return spec
    return cluster_spec(bin_dir=ensure_engine_binaries(emit))


__all__ = [
    "LOCAL_DBNAME",
    "LOCAL_SUPERUSER",
    "LOCAL_UNIVERSE_DIR_NAME",
    "LocalUniverseError",
    "birth",
    "cluster_spec",
    "ensure_database",
    "ensure_engine_binaries",
    "is_born",
    "local_dsn",
    "pinned_authority",
    "start",
    "status",
    "stop",
    "universe_root",
]
