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
import re
import subprocess
import sys
from typing import Optional, Sequence


DEFAULT_PARALLEL_WORKERS = "auto"
LOW_CAPACITY_PARALLEL_WORKERS = "1"
DEFAULT_RAM_THRESHOLD_MB = 3 * 1024
DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS = "10"

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
    dsn = env.get("YOKE_PG_DSN")
    if not dsn:
        return
    try:
        from yoke_core.tools import pg_testcluster
    except Exception:
        return
    cluster_root = env.get("YOKE_PG_CLUSTER_ROOT")
    prior_root = os.environ.get("YOKE_PG_CLUSTER_ROOT")
    if cluster_root:
        os.environ["YOKE_PG_CLUSTER_ROOT"] = cluster_root
    try:
        if dsn != pg_testcluster.dsn():
            return
        pg_testcluster.prepare_for_pytest()
    finally:
        if cluster_root:
            if prior_root is None:
                os.environ.pop("YOKE_PG_CLUSTER_ROOT", None)
            else:
                os.environ["YOKE_PG_CLUSTER_ROOT"] = prior_root


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
        DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS,
    )
    if workers:
        resolved[PYTEST_XDIST_AUTO_WORKERS_ENV] = workers
        _prepare_local_pg_testcluster(resolved)
    return resolved


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
    """Return reclaimable free RAM in MB, or None when unknowable.

    macOS uses ``vm_stat`` (sum of free, inactive, speculative, and
    purgeable pages — all reclaimable without disk I/O). Linux reads
    ``MemAvailable`` from ``/proc/meminfo``. Other platforms return
    ``None`` so callers fall back to the high-capacity default.
    """
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, TypeError):
            # TypeError surfaces when subprocess.run has been monkeypatched
            # by a test fixture whose signature does not accept the kwargs
            # passed here. Treat as "unknowable RAM" and fall back to the
            # high-capacity default — same outcome as the other branches.
            return None
        if result.returncode != 0:
            return None
        page_size = 4096
        page_size_match = re.search(
            r"page size of (\d+) bytes", result.stdout
        )
        if page_size_match:
            page_size = int(page_size_match.group(1))
        pages = 0
        for key in (
            "Pages free",
            "Pages inactive",
            "Pages speculative",
            "Pages purgeable",
        ):
            match = re.search(rf"{re.escape(key)}:\s+(\d+)", result.stdout)
            if match:
                pages += int(match.group(1))
        if pages == 0:
            return None
        return (pages * page_size) // (1024 * 1024)
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return int(parts[1]) // 1024
        except OSError:
            return None
        return None
    return None


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
        threshold = (
            int(threshold_env) if threshold_env else DEFAULT_RAM_THRESHOLD_MB
        )
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
