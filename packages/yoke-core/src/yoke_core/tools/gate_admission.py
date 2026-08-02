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
additional invocation waits — printing its status — until a slot frees
or the wait bound expires. An admitted gate runs near its solo
wall-clock; a waiting gate is slow but safe, and total machine
throughput is strictly higher than under thrashing.

Queueing is only ever correct between peers. A descendant that waits on
a slot its own ancestor is blocking on is not queued, it is deadlocked,
so this module tracks what the ancestor actually holds rather than
whether an ancestor exists at all (see :data:`ADMITTED_ENV`).

Mechanics:

- Slots are session-scoped PostgreSQL advisory locks on the shared test
  cluster's maintenance database. The contended resource arbitrates its
  own access: no lock files, no daemon, and a crashed holder's lock
  vanishes with its connection, so slots can never leak.
- HEAVY means the invocation sweeps directories (any directory-shaped
  path argument, or no path arguments at all — a bare run covers the
  whole rootdir). File-scoped runs are cheap on every axis and bypass
  admission entirely.
- Waiting is bounded. A gate that never gets a slot within
  ``test_gate_timeout.wait_timeout_seconds()`` proceeds without one and
  says so, because a hung queue is worse than an oversubscribed machine.
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

#: Set for the duration of any gate that has resolved its own admission,
#: and inherited by every process it spawns. The value states what the
#: ancestor actually holds, because a descendant's correct behavior differs
#: by case and "an ancestor exists" cannot distinguish them: riding a slot
#: the ancestor holds is free, while queueing behind a stranger's slot when
#: the ancestor holds nothing is a deadlock — the ancestor cannot finish
#: until the descendant does.
ADMITTED_ENV = "YOKE_TEST_GATE_SLOT_HELD"

#: The ancestor holds a real slot; descendants ride it.
MARKER_SLOT_HELD = "slot"

#: The ancestor resolved admission without holding a slot — it was
#: file-scoped, the cap was disabled, or no cluster was reachable.
MARKER_NO_SLOT = "bypass"

#: Base advisory-lock key for gate slots; slot *i* locks ``BASE + i``.
#: Distinct from the cluster-role authority lock used by the fixtures.
GATE_SLOT_LOCK_BASE = 0x596F6B6547617431

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


def ancestor_admission_state() -> Optional[str]:
    """Return what an admitted ancestor holds, or None when there is none.

    Any marker value other than :data:`MARKER_NO_SLOT` reads as a held slot,
    so a process spawned by an older build that wrote a bare truthy marker
    still rides its ancestor rather than arbitrating a second time.
    """
    marker = os.environ.get(ADMITTED_ENV)
    if not marker:
        return None
    return MARKER_NO_SLOT if marker == MARKER_NO_SLOT else MARKER_SLOT_HELD


@contextlib.contextmanager
def _published_state(state: str) -> Iterator[None]:
    """Publish *state* to descendants for the duration of the block."""
    prior = os.environ.get(ADMITTED_ENV)
    os.environ[ADMITTED_ENV] = state
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(ADMITTED_ENV, None)
        else:
            os.environ[ADMITTED_ENV] = prior


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


def _acquire(stream: TextIO):
    """Wait for a gate slot; return the holding connection.

    Returns None to proceed without admission (disabled cap, unreachable
    cluster, missing driver, or an expired wait bound) — availability of
    the gate wins.
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
    wait_bound = test_gate_timeout.wait_timeout_seconds()
    waited_since = time.monotonic()
    last_announce = 0.0
    try:
        while True:
            # The lock base is read from the module at call time so a test
            # can retarget the whole gate onto a scratch key range.
            if try_acquire_slot(conn, cap, GATE_SLOT_LOCK_BASE):
                waited = time.monotonic() - waited_since
                if waited > _POLL_INTERVAL_S:
                    print(
                        f"{test_gate_timeout.SLOT_ACQUIRED_PREFIX}{waited:.0f}s",
                        file=stream,
                        flush=True,
                    )
                return conn
            now = time.monotonic()
            waited = now - waited_since
            if waited >= wait_bound:
                print(
                    f"gate admission: no slot after {waited:.0f}s "
                    f"(bound {wait_bound:.0f}s); proceeding without one. "
                    f"The {cap} slot(s) are held by unrelated gates that "
                    "outlasted the bound — this run is no longer serialized "
                    "against them.",
                    file=stream,
                    flush=True,
                )
                conn.close()
                return None
            if now - last_announce >= _WAIT_ANNOUNCE_INTERVAL_S:
                print(
                    f"gate admission: {cap} heavy gates already running; "
                    f"waiting ({waited:.0f}s so far)",
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

    Three inherited situations, three behaviors: a descendant of a
    slot-holder rides that slot, a descendant of an ancestor that holds
    nothing proceeds straight away rather than deadlocking behind a
    stranger's slot, and a run with no admitted ancestor arbitrates for
    itself under a bounded wait. Narrow (file-scoped) invocations never
    touch the cluster, but they still publish what they hold — nothing —
    so their own descendants can tell the second case from the third.
    The slot rides a dedicated connection, so process death at any point
    releases it.
    """
    inherited = ancestor_admission_state()
    if inherited == MARKER_SLOT_HELD:
        yield
        return
    if not is_heavy_invocation(pytest_args):
        with _published_state(MARKER_NO_SLOT):
            yield
        return
    if inherited == MARKER_NO_SLOT:
        print(
            "gate admission: ancestor bypassed admission and holds no slot; "
            "proceeding without arbitrating for one, because that ancestor "
            "cannot finish until this run does.",
            file=stream,
            flush=True,
        )
        with _published_state(MARKER_NO_SLOT):
            yield
        return
    conn = _acquire(stream)
    try:
        with _published_state(
            MARKER_SLOT_HELD if conn is not None else MARKER_NO_SLOT
        ):
            yield
    finally:
        if conn is not None:
            conn.close()


__all__ = [
    "ADMITTED_ENV",
    "MARKER_NO_SLOT",
    "MARKER_SLOT_HELD",
    "admitted_environment",
    "ancestor_admission_state",
    "CAP_ENV",
    "CAP_MACHINE_CONFIG_KEY",
    "DEFAULT_MAX_CONCURRENT_GATES",
    "GATE_SLOT_LOCK_BASE",
    "admitted_gate",
    "is_heavy_invocation",
    "try_acquire_slot",
]
