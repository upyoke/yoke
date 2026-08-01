"""Machine-wide admission control for heavy test-gate invocations.

Every concurrent pytest gate on a machine shares one disposable Postgres
cluster, one CPU complement, and one memory budget. Uncapped, N full
suites each spawn their own xdist worker fleet: measured on an 18-core /
48 GB machine, four concurrent full gates saturate the CPU (load 17) and
hold ~11 cluster connections each — at ~18 gates the cluster's
``max_connections`` is exhausted and suites start dying with hard
"too many clients" failures rather than merely slowing down.

Admission control turns that collapse into an orderly queue: at most a
bounded number of HEAVY gate invocations execute at once, and every
additional invocation waits — printing its status — until a slot frees.
An admitted gate runs near its solo wall-clock; a waiting gate is slow
but safe, and total machine throughput is strictly higher than under
thrashing.

Mechanics:

- Slots are session-scoped PostgreSQL advisory locks on the shared test
  cluster's maintenance database. The contended resource arbitrates its
  own access: no lock files, no daemon, and a crashed holder's lock
  vanishes with its connection, so slots can never leak.
- HEAVY means the invocation sweeps directories (any directory-shaped
  path argument, or no path arguments at all — a bare run covers the
  whole rootdir). File-scoped runs are cheap on every axis and bypass
  admission entirely.
- The cap resolves from the ``YOKE_TEST_GATE_MAX_CONCURRENT`` env var,
  then the ``test_gate_max_concurrent`` machine-config key, then the
  default. Zero or negative disables admission.
- Fail-open: when no cluster can be reached (no local cluster tooling,
  no DSN), the gate proceeds without a slot after a warning. Admission
  is a throughput guard, not a correctness gate.
"""

from __future__ import annotations

import contextlib
import os
import random
import sys
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence, TextIO

# Measured on the 18-core / 48 GB reference machine: two concurrent full
# gates run at ~1.55x solo wall-clock with no failures and slightly beat
# solo throughput; four run at ~6x solo and deterministically bust the
# suite's tight real-time deadlines (SIGINT-cleanup budgets, subprocess
# spawn deadlines). Larger machines raise this via machine config.
DEFAULT_MAX_CONCURRENT_GATES = 2

CAP_ENV = "YOKE_TEST_GATE_MAX_CONCURRENT"
CAP_MACHINE_CONFIG_KEY = "test_gate_max_concurrent"

#: Base advisory-lock key for gate slots; slot *i* locks ``BASE + i``.
#: Distinct from the cluster-role authority lock used by the fixtures.
GATE_SLOT_LOCK_BASE = 0x596F6B6547617431

_WAIT_ANNOUNCE_INTERVAL_S = 15.0
_POLL_INTERVAL_S = 2.0


def is_heavy_invocation(pytest_args: Sequence[str]) -> bool:
    """Return True when the invocation sweeps directories (or the rootdir).

    Positional arguments that exist on disk are treated as paths; any
    directory among them makes the run heavy. Flags and flag values
    (``-n auto``, ``-k expr``) do not exist on disk and fall through.
    """
    saw_path = False
    for arg in pytest_args:
        if arg.startswith("-"):
            continue
        candidate = Path(arg.split("::", 1)[0])
        if candidate.is_dir():
            return True
        if candidate.exists():
            saw_path = True
    return not saw_path


def _resolve_cap() -> int:
    raw = os.environ.get(CAP_ENV)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    try:
        from yoke_contracts.machine_config import runtime as machine_config

        configured = machine_config.load_config().get(CAP_MACHINE_CONFIG_KEY)
        if configured is not None:
            return int(configured)
    except Exception:
        pass
    return DEFAULT_MAX_CONCURRENT_GATES


def _maintenance_dsn() -> Optional[str]:
    """DSN for the shared cluster's maintenance database, or None."""
    try:
        from yoke_core.domain import db_backend

        if os.environ.get(db_backend.PG_DSN_ENV) or os.environ.get(
            db_backend.PG_DSN_FILE_ENV
        ):
            base = db_backend.resolve_pg_dsn()
        else:
            from yoke_core.tools import pg_testcluster

            if pg_testcluster.ensure_started() != 0:
                return None
            base = pg_testcluster.dsn()
    except Exception:
        return None
    # libpq key/value DSN: a later dbname= key wins, so appending overrides.
    return f"{base} dbname=postgres"


def try_acquire_slot(conn, cap: int, base: int = GATE_SLOT_LOCK_BASE) -> bool:
    """Try to take any of the *cap* gate slots on *conn*'s session.

    *base* selects the advisory-lock key range; tests pass a scratch base
    so slot-exhaustion scenarios never collide with live gate slots on the
    shared cluster.
    """
    for slot in range(cap):
        (got,) = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (base + slot,)
        ).fetchone()
        if got:
            return True
    return False


def _acquire(stream: TextIO):
    """Block until a gate slot is held; return the holding connection.

    Returns None to proceed without admission (disabled cap, unreachable
    cluster, or missing driver) — availability of the gate wins.
    """
    cap = _resolve_cap()
    if cap <= 0:
        return None
    dsn = _maintenance_dsn()
    if dsn is None:
        print(
            "gate admission: no shared test cluster reachable; "
            "proceeding without a slot",
            file=stream,
            flush=True,
        )
        return None
    try:
        import psycopg

        conn = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:
        print(
            f"gate admission: cannot connect for slot arbitration ({exc}); "
            "proceeding without a slot",
            file=stream,
            flush=True,
        )
        return None
    waited_since = time.monotonic()
    last_announce = 0.0
    try:
        while True:
            if try_acquire_slot(conn, cap):
                waited = time.monotonic() - waited_since
                if waited > _POLL_INTERVAL_S:
                    print(
                        f"gate admission: slot acquired after {waited:.0f}s",
                        file=stream,
                        flush=True,
                    )
                return conn
            now = time.monotonic()
            if now - last_announce >= _WAIT_ANNOUNCE_INTERVAL_S:
                print(
                    f"gate admission: {cap} heavy gates already running; "
                    f"waiting ({now - waited_since:.0f}s so far)",
                    file=stream,
                    flush=True,
                )
                last_announce = now
            time.sleep(_POLL_INTERVAL_S + random.uniform(0.0, 1.0))
    except BaseException:
        conn.close()
        raise


@contextlib.contextmanager
def admitted_gate(
    pytest_args: Sequence[str], stream: TextIO = sys.stderr
) -> Iterator[None]:
    """Hold a machine-wide gate slot for the duration of a heavy run.

    Narrow (file-scoped) invocations pass through without touching the
    cluster. The slot rides a dedicated connection, so process death at
    any point releases it.
    """
    if not is_heavy_invocation(pytest_args):
        yield
        return
    conn = _acquire(stream)
    try:
        yield
    finally:
        if conn is not None:
            conn.close()


__all__ = [
    "CAP_ENV",
    "CAP_MACHINE_CONFIG_KEY",
    "DEFAULT_MAX_CONCURRENT_GATES",
    "GATE_SLOT_LOCK_BASE",
    "admitted_gate",
    "is_heavy_invocation",
    "try_acquire_slot",
]
