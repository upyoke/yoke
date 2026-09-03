"""Shared helper for the default-parallel pytest invocation contract.

Both ``run_tests`` and ``watch_pytest`` ship with pytest-xdist's ``-n auto``
on by default so every agent and operator invocation inherits the speedup
from a single code edit, not a per-prompt teaching loop. Callers opt out
in two ways:

- The wrapper-level ``--no-parallel`` flag (cleaner for operators who
  want to debug order-sensitivity without remembering xdist syntax).
- Explicit ``-n N`` / ``--numprocesses N`` in the pytest pass-through
  (caller-supplied worker count wins; the helper does not second-guess).

The injected default is RAM-aware: above
``DEFAULT_RAM_THRESHOLD_MB`` of free physical memory it stays
``"auto"``; below that cliff it drops to ``"1"`` so a stressed box does
not compound oversubscription. Operators force a specific value with
``YOKE_PYTEST_WORKERS`` (wins absolutely) and retune the cliff via
``YOKE_PYTEST_RAM_THRESHOLD_MB``.

For local Postgres verification, pytest-xdist's ``auto`` can oversubscribe the
disposable cluster because CPU count is not a database connection budget. Yoke
authority tests are Postgres-only, so the watcher/run-tests wrappers set xdist's
own ``PYTEST_XDIST_AUTO_NUM_WORKERS`` env var to a fast local default when
xdist is using ``auto``, the run is not CI, and the operator has not already set
that env var. Explicit ``-n 10`` and ``YOKE_PYTEST_WORKERS=10`` still pass
through untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Optional, Sequence

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.machine_capacity import free_memory_bytes


DEFAULT_PARALLEL_WORKERS = "auto"
LOW_CAPACITY_PARALLEL_WORKERS = "1"
DEFAULT_RAM_THRESHOLD_MB = 3 * 1024
DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS = "10"

#: Worker count for a file-scoped run on the local cluster. Such a run is
#: deliberately exempt from gate admission so a quick check stays quick
#: while a full gate holds the slot — but the exemption is worthless if the
#: quick check then claims the same worker fleet as the gate and both
#: crawl. A small fleet keeps it fast in wall-clock terms (few files, few
#: workers) without competing for the machine.
NARROW_LOCAL_POSTGRES_AUTO_WORKERS = "4"

NO_PARALLEL_FLAG = "--no-parallel"
PYTEST_XDIST_AUTO_WORKERS_ENV = "PYTEST_XDIST_AUTO_NUM_WORKERS"
LOCAL_POSTGRES_AUTO_WORKERS_ENV = "YOKE_PG_PYTEST_AUTO_WORKERS"

_PYTEST_WORKERS_FLAGS = ("-n", "--numprocesses")


def has_explicit_workers(args: Sequence[str]) -> bool:
    """Return True when ``args`` already names a pytest-xdist worker count."""
    for arg in args:
        if arg in _PYTEST_WORKERS_FLAGS:
            return True
        for flag in _PYTEST_WORKERS_FLAGS:
            if arg.startswith(f"{flag}="):
                return True
    return False


def uses_xdist_auto_workers(args: Sequence[str]) -> bool:
    """Return True when ``args`` request pytest-xdist's ``auto`` worker count."""
    for index, arg in enumerate(args):
        if arg in _PYTEST_WORKERS_FLAGS:
            if index + 1 < len(args) and args[index + 1] == DEFAULT_PARALLEL_WORKERS:
                return True
            continue
        for flag in _PYTEST_WORKERS_FLAGS:
            if arg == f"{flag}={DEFAULT_PARALLEL_WORKERS}":
                return True
    return False


def _prepare_local_pg_testcluster(env: dict[str, str]) -> None:
    """Start the local test cluster and reclaim orphans before workers spawn.

    ``YOKE_PG_DSN`` is normally ABSENT here. The suite's conftest binds it to
    the test cluster at import time, inside the pytest process — long after
    this parent-process decision is made. Treating an unset value as "not the
    test cluster" therefore skipped the sweep on every ordinary local run,
    letting databases orphaned by interrupted runs accumulate until cloning a
    template slowed enough to stall every xdist worker behind the maintenance
    lock. Absence means the conftest will bind this cluster, so sweep it; only
    a DSN that explicitly names a DIFFERENT cluster is a reason to skip.

    The sweep only ever reclaims databases whose owning invocation has exited,
    so running it here cannot disturb a suite already in flight.
    """
    try:
        from yoke_core.tools import pg_testcluster
    except Exception:
        return
    dsn = env.get("YOKE_PG_DSN")
    cluster_root = env.get("YOKE_PG_CLUSTER_ROOT")
    prior_root = os.environ.get("YOKE_PG_CLUSTER_ROOT")
    if cluster_root:
        os.environ["YOKE_PG_CLUSTER_ROOT"] = cluster_root
    try:
        if dsn and dsn != pg_testcluster.dsn():
            return
        pg_testcluster.prepare_for_pytest()
    finally:
        if cluster_root:
            if prior_root is None:
                os.environ.pop("YOKE_PG_CLUSTER_ROOT", None)
            else:
                os.environ["YOKE_PG_CLUSTER_ROOT"] = prior_root


def _local_postgres_auto_workers(args: Sequence[str]) -> str:
    """Worker count for this invocation's shape on the local cluster."""
    from yoke_core.tools.gate_admission import is_heavy_invocation

    if is_heavy_invocation(args):
        return DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS
    return NARROW_LOCAL_POSTGRES_AUTO_WORKERS


def apply_postgres_xdist_auto_env(
    args: Sequence[str],
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return env with local Postgres ``-n auto`` resolved to a safe fast count.

    This does not rewrite the visible pytest argv. Instead it uses xdist's
    supported ``PYTEST_XDIST_AUTO_NUM_WORKERS`` hook so callers can keep saying
    ``-n auto`` while the local Postgres test cluster avoids connection storms.
    CI keeps the platform CPU-derived ``auto`` value; GitHub's matrix currently
    resolves that to two workers and is already green.

    The count also depends on the invocation's shape: a full sweep gets the
    fast fleet, while a file-scoped run — which bypasses gate admission and
    so may be sharing the machine with a running gate — gets a small one.
    """
    resolved = dict(os.environ if env is None else env)
    if not uses_xdist_auto_workers(args):
        return resolved
    if resolved.get("CI"):
        return resolved
    if resolved.get(PYTEST_XDIST_AUTO_WORKERS_ENV):
        return resolved

    workers = resolved.get(
        LOCAL_POSTGRES_AUTO_WORKERS_ENV,
        _local_postgres_auto_workers(args),
    )
    if workers:
        resolved[PYTEST_XDIST_AUTO_WORKERS_ENV] = workers
        _prepare_local_pg_testcluster(resolved)
    return resolved


def isolate_from_administering_machine_config(env: dict[str, str]) -> dict[str, str]:
    """Hide the parent's machine config from a pytest child.

    ``environment_without_administering_selection`` swaps a ``*-db-admin``
    selection for its served sibling. When that sibling — or the original
    selection — is itself prod-flagged (hosted HTTPS ``prod``), the child
    would still refuse fixture-owned schema work. An empty machine home drops
    that ambient authority without pointing the suite at another universe;
    an endpoint-only inventory still lets concrete target guards recognize an
    explicitly named administered cluster.
    """
    from yoke_core.domain import administered_postgres

    isolated = administered_postgres.environment_with_administered_target_inventory(env)
    isolated[machine_config_runtime.HOME_ENV] = tempfile.mkdtemp(
        prefix="yoke-pytest-non-admin-"
    )
    isolated.pop(machine_config_runtime.CONFIG_FILE_ENV, None)
    if not isolated.get("YOKE_SESSION_ID"):
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        session_id = resolve_ambient_session_id()
        if session_id:
            isolated["YOKE_SESSION_ID"] = session_id
    return isolated


def split_no_parallel(args: Sequence[str]) -> tuple[bool, list[str]]:
    """Strip ``--no-parallel`` from ``args``; return ``(found, cleaned)``."""
    cleaned: list[str] = []
    found = False
    for arg in args:
        if arg == NO_PARALLEL_FLAG:
            found = True
            continue
        cleaned.append(arg)
    return found, cleaned


def _read_free_ram_mb() -> Optional[int]:
    """Reclaimable free RAM in MB from the shared machine probe, or None."""
    free_bytes = free_memory_bytes()
    return None if free_bytes is None else free_bytes // (1024 * 1024)


def choose_default_workers() -> str:
    """Resolve the worker count for ``-n`` injection.

    ``YOKE_PYTEST_WORKERS`` wins absolutely (operator escape hatch).
    Otherwise picks ``DEFAULT_PARALLEL_WORKERS`` when free RAM is at
    or above the threshold, ``LOW_CAPACITY_PARALLEL_WORKERS`` when
    below it, and falls back to the high-capacity default when the
    free-RAM reader returns ``None``.
    """
    override = os.environ.get("YOKE_PYTEST_WORKERS")
    if override:
        return override
    free_mb = _read_free_ram_mb()
    if free_mb is None:
        return DEFAULT_PARALLEL_WORKERS
    threshold_env = os.environ.get("YOKE_PYTEST_RAM_THRESHOLD_MB")
    try:
        threshold = int(threshold_env) if threshold_env else DEFAULT_RAM_THRESHOLD_MB
    except ValueError:
        threshold = DEFAULT_RAM_THRESHOLD_MB
    if free_mb >= threshold:
        return DEFAULT_PARALLEL_WORKERS
    sys.stderr.write(
        f"watch_pytest: free RAM {free_mb} MB < threshold {threshold} MB; "
        f"using -n {LOW_CAPACITY_PARALLEL_WORKERS} "
        f"(was -n {DEFAULT_PARALLEL_WORKERS})\n"
    )
    return LOW_CAPACITY_PARALLEL_WORKERS


def apply_parallel_default(
    args: Sequence[str],
    *,
    no_parallel: bool = False,
) -> list[str]:
    """Return ``args`` with ``-n <workers>`` prepended unless an override applies.

    ``no_parallel=True`` skips injection entirely. Explicit ``-n``/
    ``--numprocesses`` in ``args`` also skips injection — the caller's
    worker count wins. When the helper does inject, the worker count
    comes from ``choose_default_workers`` (RAM-aware cliff).
    """
    if no_parallel:
        return list(args)
    if has_explicit_workers(args):
        return list(args)
    return ["-n", choose_default_workers(), *args]
