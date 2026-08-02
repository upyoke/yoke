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
- Observable: each arbitration connection stamps its state onto its own
  ``application_name``, so a queued gate reports who holds the slot and
  how many runs are queued instead of only that it is waiting. The
  cluster tracks connections already; a crashed run's entry disappears
  with its connection, exactly like its slot.
"""

from __future__ import annotations

import contextlib
import os
import random
import sys
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence, TextIO

from yoke_core.domain import test_gate_timeout

# One gate already claims most of the machine: pytest-xdist sizes its
# worker fleet from the core count, so a single full gate runs ~10 workers
# on the 18-core reference machine. A second concurrent gate therefore
# oversubscribes the CPU rather than using spare capacity — measured at
# two gates, each runs ~1.55x its solo wall-clock and the machine has
# nothing left for the interactive work happening alongside it. Serializing
# gates costs roughly the same total drain time (each runs at full speed
# instead of half) while keeping every individual gate predictable and the
# machine responsive. Bigger machines raise this via machine config.
DEFAULT_MAX_CONCURRENT_GATES = 1

CAP_ENV = "YOKE_TEST_GATE_MAX_CONCURRENT"
CAP_MACHINE_CONFIG_KEY = "test_gate_max_concurrent"

#: Set for the duration of an admitted heavy gate and inherited by every
#: process it spawns. A descendant invocation rides its ancestor's slot
#: instead of arbitrating its own: the suite's own tool tests spawn real
#: nested runner invocations, and a nested invocation waiting on the slot
#: its ancestor holds is a deadlock, not a queue.
ADMITTED_ENV = "YOKE_TEST_GATE_SLOT_HELD"

#: Base advisory-lock key for gate slots; slot *i* locks ``BASE + i``.
#: Distinct from the cluster-role authority lock used by the fixtures.
GATE_SLOT_LOCK_BASE = 0x596F6B6547617431

#: Prefixes stamped on each arbitration connection's ``application_name``.
#: The contended resource already tracks every connection, so its own
#: activity view answers "who holds the slot?" and "how many runs are
#: queued behind it?" — a queued run can say why it is waiting without a
#: second bookkeeping surface that could outlive the process it describes.
SLOT_HELD_APP_PREFIX = "yoke-gate-held:"
SLOT_WAIT_APP_PREFIX = "yoke-gate-wait:"

_WAIT_ANNOUNCE_INTERVAL_S = 15.0
_POLL_INTERVAL_S = 2.0


def admitted_environment(env: dict) -> dict:
    """Return *env* with the current admission marker mirrored in.

    Wrappers snapshot their child environment before entering the
    admission context, so the marker :func:`admitted_gate` sets on
    ``os.environ`` must be re-mirrored into that snapshot at spawn time —
    otherwise descendants never see it and arbitrate their own slots,
    deadlocking behind their ancestor.
    """
    marker = os.environ.get(ADMITTED_ENV)
    if marker:
        return {**env, ADMITTED_ENV: marker}
    return env


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
        from yoke_core.domain.runtime_settings import get_int

        return get_int(CAP_MACHINE_CONFIG_KEY, DEFAULT_MAX_CONCURRENT_GATES)
    except Exception:
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


def slot_identity() -> str:
    """Name this invocation for the shared cluster's activity view.

    The working directory is the useful half — on a fleet of worktrees it
    is what tells one queued gate from another — and the pid disambiguates
    two runs in the same tree.
    """
    try:
        tree = Path.cwd().name or "unknown"
    except OSError:
        tree = "unknown"
    return f"{tree}/pid{os.getpid()}"


def _stamp_activity(conn, prefix: str, identity: str) -> None:
    """Publish this connection's admission state; never fail the gate.

    ``set_config`` rather than ``SET`` because the value is a parameter —
    the identity carries a directory name this module does not control.
    """
    try:
        conn.execute(
            "SELECT set_config('application_name', %s, false)",
            (f"{prefix}{identity}",),
        )
    except Exception:
        pass


def slot_occupancy(conn) -> tuple[list[str], int]:
    """Return ``(holder identities, waiting connection count)``."""
    try:
        rows = conn.execute(
            "SELECT application_name FROM pg_stat_activity "
            "WHERE application_name LIKE %s OR application_name LIKE %s",
            (f"{SLOT_HELD_APP_PREFIX}%", f"{SLOT_WAIT_APP_PREFIX}%"),
        ).fetchall()
    except Exception:
        return ([], 0)
    names = [str(row[0]) for row in rows]
    holders = [
        name[len(SLOT_HELD_APP_PREFIX):]
        for name in names
        if name.startswith(SLOT_HELD_APP_PREFIX)
    ]
    waiting = sum(1 for name in names if name.startswith(SLOT_WAIT_APP_PREFIX))
    return (sorted(holders), waiting)


def waiting_announcement(
    cap: int, waited_seconds: float, holders: Sequence[str], waiting: int,
) -> str:
    """Say who holds the slot and how deep the queue is, not just that we wait."""
    who = ", ".join(holders) if holders else "a run that did not name itself"
    # This connection is itself one of the waiters in the view.
    ahead = max(0, waiting - 1)
    queue = f"; {ahead} other queued run(s)" if ahead else ""
    return (
        f"gate admission: {cap} heavy gate slot(s) held by {who}{queue}; "
        f"waiting ({waited_seconds:.0f}s so far)"
    )


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
    identity = slot_identity()
    _stamp_activity(conn, SLOT_WAIT_APP_PREFIX, identity)
    waited_since = time.monotonic()
    last_announce = 0.0
    try:
        while True:
            # The lock base is read from the module at call time so a test
            # can retarget the whole gate onto a scratch key range.
            if try_acquire_slot(conn, cap, GATE_SLOT_LOCK_BASE):
                _stamp_activity(conn, SLOT_HELD_APP_PREFIX, identity)
                waited = time.monotonic() - waited_since
                if waited > _POLL_INTERVAL_S:
                    print(
                        f"{test_gate_timeout.SLOT_ACQUIRED_PREFIX}{waited:.0f}s",
                        file=stream,
                        flush=True,
                    )
                return conn
            now = time.monotonic()
            if now - last_announce >= _WAIT_ANNOUNCE_INTERVAL_S:
                holders, waiting = slot_occupancy(conn)
                print(
                    waiting_announcement(
                        cap, now - waited_since, holders, waiting,
                    ),
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
    cluster, and descendants of an already-admitted gate ride their
    ancestor's slot (see :data:`ADMITTED_ENV`). The slot rides a
    dedicated connection, so process death at any point releases it.
    """
    if not is_heavy_invocation(pytest_args) or os.environ.get(ADMITTED_ENV):
        yield
        return
    conn = _acquire(stream)
    prior_marker = os.environ.get(ADMITTED_ENV)
    os.environ[ADMITTED_ENV] = "1"
    try:
        yield
    finally:
        if prior_marker is None:
            os.environ.pop(ADMITTED_ENV, None)
        else:
            os.environ[ADMITTED_ENV] = prior_marker
        if conn is not None:
            conn.close()


__all__ = [
    "ADMITTED_ENV",
    "admitted_environment",
    "CAP_ENV",
    "CAP_MACHINE_CONFIG_KEY",
    "DEFAULT_MAX_CONCURRENT_GATES",
    "GATE_SLOT_LOCK_BASE",
    "SLOT_HELD_APP_PREFIX",
    "SLOT_WAIT_APP_PREFIX",
    "admitted_gate",
    "is_heavy_invocation",
    "slot_identity",
    "slot_occupancy",
    "try_acquire_slot",
    "waiting_announcement",
]
