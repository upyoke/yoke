"""One machine-wide budget of pytest-xdist workers for local test runs.

The heavy-gate slot in :mod:`yoke_core.tools.gate_admission` serialises
directory sweeps, but a file-scoped run bypasses it on purpose, and six
lanes each running a file-scoped impacted selection at ``-n 4`` — plus the
``yoke`` interpreters those tests shell out to — put 91 Python processes
and a load of 48 on an 18-core machine. No single run was heavy; the sum
was.

So every local pytest run, whichever entry point starts it, takes its
worker count out of one budget: by default as many workers as the machine
has cores, tunable per machine. A run takes what is free up to what it
asked for and runs with that many workers; when nothing is free it waits,
naming who holds the budget; and when the one-minute load already exceeds
the core count it asks for half. The budget is arbitrated the way the gate
slot is — session-scoped advisory locks on the shared test cluster, one
per worker, so a crashed run's workers return with its connection — and,
like the slot, it fails open when no cluster can be reached: it is a
throughput guard, not a correctness gate.
"""

from __future__ import annotations

import contextlib
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Iterator, Mapping, Optional, Sequence, TextIO

from yoke_core.domain import qa_gate_timeout
from yoke_core.tools import gate_admission
from yoke_core.tools._pytest_parallel import (
    PYTEST_XDIST_AUTO_WORKERS_ENV,
    explicit_workers,
    with_workers,
)
from yoke_core.tools.gate_slot_observability import _stamp_activity, slot_identity

BUDGET_ENV = "YOKE_PYTEST_WORKER_BUDGET"
BUDGET_MACHINE_CONFIG_KEY = "pytest_worker_budget"
#: Published to descendants for the duration of a run that has resolved its
#: grant; a pytest a test spawns rides its ancestor rather than queueing
#: behind it.
HELD_ENV = "YOKE_PYTEST_WORKERS_HELD"
#: Advisory-lock key range; worker *i* locks ``BASE + i``. Distinct from the
#: gate-slot range so a held slot and a held worker never alias.
WORKER_LOCK_BASE = 0x596F6B65576F726B
LOCK_BASE_ENV = "YOKE_PYTEST_WORKER_LOCK_BASE"
HELD_APP_PREFIX = "yoke-workers-held:"
WAIT_APP_PREFIX = "yoke-workers-wait:"
LOG_PREFIX = "pytest worker budget:"

_WAIT_ANNOUNCE_INTERVAL_S = 15.0
_POLL_INTERVAL_S = 2.0


def core_count() -> int:
    return max(1, os.cpu_count() or 1)


def budget_size(env: Mapping[str, str] | None = None) -> int:
    """Workers this machine lends out at once; zero or less disables."""
    raw = (os.environ if env is None else env).get(BUDGET_ENV)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    try:
        from yoke_core.domain.runtime_settings import get_int

        return get_int(BUDGET_MACHINE_CONFIG_KEY, core_count())
    except Exception:  # noqa: BLE001 - an unreadable config keeps the default
        return core_count()


def requested_workers(pytest_args: Sequence[str], env: Mapping[str, str]) -> int:
    """Workers *pytest_args* would start: an explicit count, or ``auto`` here."""
    explicit = explicit_workers(pytest_args)
    if explicit is None:
        return 1
    if explicit != "auto":
        try:
            return max(1, int(explicit))
        except ValueError:
            return 1
    raw = env.get(PYTEST_XDIST_AUTO_WORKERS_ENV)
    try:
        return max(1, int(raw)) if raw else core_count()
    except ValueError:
        return core_count()


def load_backoff(
    request: int, *, load: float | None = None, cores: int | None = None,
) -> tuple[int, str | None]:
    """Halve the request when the machine is already over its cores."""
    cores = cores or core_count()
    if load is None:
        try:
            load = os.getloadavg()[0]
        except (AttributeError, OSError):
            return request, None
    if load <= cores or request <= 1:
        return request, None
    granted = max(1, request // 2)
    return granted, (
        f"{LOG_PREFIX} 1-minute load {load:.1f} exceeds {cores} cores; "
        f"requesting {granted} worker(s) instead of {request}"
    )


def lock_base() -> int:
    raw = os.environ.get(LOCK_BASE_ENV)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return WORKER_LOCK_BASE


def take_workers(conn, request: int, budget: int, base: int | None = None) -> int:
    """Lock up to *request* of the *budget* worker keys on *conn*'s session."""
    keys = lock_base() if base is None else base
    taken = 0
    for index in range(budget):
        if taken >= request:
            break
        (got,) = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (keys + index,)
        ).fetchone()
        if got:
            taken += 1
    return taken


def holders(conn) -> tuple[list[str], int]:
    """Return ``(holder identities, waiting connection count)``."""
    try:
        rows = conn.execute(
            "SELECT application_name FROM pg_stat_activity "
            "WHERE application_name LIKE %s OR application_name LIKE %s",
            (f"{HELD_APP_PREFIX}%", f"{WAIT_APP_PREFIX}%"),
        ).fetchall()
    except Exception:  # noqa: BLE001 - observability never fails the run
        return [], 0
    names = [str(row[0]) for row in rows]
    held = sorted(n[len(HELD_APP_PREFIX):] for n in names if n.startswith(HELD_APP_PREFIX))
    waiting = sum(1 for n in names if n.startswith(WAIT_APP_PREFIX))
    return held, waiting


def waiting_announcement(
    budget: int, waited_seconds: float, held: Sequence[str], waiting: int,
) -> str:
    """Say who holds the workers and how deep the queue is."""
    who = ", ".join(held) if held else "a run that did not name itself"
    ahead = max(0, waiting - 1)
    queue = f"; {ahead} other queued run(s)" if ahead else ""
    return (
        f"{LOG_PREFIX} all {budget} worker(s) held by {who}{queue}; "
        f"waiting ({waited_seconds:.0f}s so far)"
    )


@dataclass
class Grant:
    """What a run may start with; ``workers`` None means ungoverned."""

    workers: Optional[int]
    requested: int

    def apply(self, pytest_args: Sequence[str]) -> list[str]:
        """*pytest_args* with the worker count the grant allows."""
        if self.workers is None or explicit_workers(pytest_args) in (None, "0"):
            return list(pytest_args)
        return with_workers(pytest_args, self.workers)

    @staticmethod
    def environment(env: Mapping[str, str]) -> dict[str, str]:
        """*env* with the held marker mirrored in for the child."""
        held = os.environ.get(HELD_ENV)
        return {**env, HELD_ENV: held} if held else dict(env)


def _acquire(request: int, stream: TextIO) -> tuple[object | None, int | None]:
    """Wait for workers; return ``(connection, granted)`` or ``(None, None)``."""
    budget = budget_size()
    if budget <= 0:
        return None, None
    dsn = gate_admission.maintenance_dsn()
    if dsn is None:
        print(f"{LOG_PREFIX} no shared test cluster reachable; running ungoverned",
              file=stream, flush=True)
        return None, None
    try:
        import psycopg

        conn = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:  # noqa: BLE001 - fail open, but say why
        print(f"{LOG_PREFIX} cannot connect for arbitration ({exc}); running ungoverned",
              file=stream, flush=True)
        return None, None
    identity = slot_identity()
    _stamp_activity(conn, WAIT_APP_PREFIX, identity)
    request = min(request, budget)
    wait_bound = qa_gate_timeout.wait_timeout_seconds()
    waited_since = time.monotonic()
    last_announce = 0.0
    try:
        while True:
            taken = take_workers(conn, request, budget)
            if taken:
                _stamp_activity(conn, HELD_APP_PREFIX, f"{identity}={taken}")
                waited = time.monotonic() - waited_since
                note = f" after waiting {waited:.0f}s" if waited > _POLL_INTERVAL_S else ""
                if taken < request or note:
                    print(f"{LOG_PREFIX} granted {taken} of {request} requested "
                          f"worker(s) (budget {budget}){note}", file=stream, flush=True)
                return conn, taken
            now = time.monotonic()
            waited = now - waited_since
            if waited >= wait_bound:
                print(f"{LOG_PREFIX} no worker freed in {waited:.0f}s (bound "
                      f"{wait_bound:.0f}s); running ungoverned", file=stream, flush=True)
                conn.close()
                return None, None
            if now - last_announce >= _WAIT_ANNOUNCE_INTERVAL_S:
                held, waiting = holders(conn)
                print(waiting_announcement(budget, waited, held, waiting),
                      file=stream, flush=True)
                last_announce = now
            time.sleep(_POLL_INTERVAL_S + random.uniform(0.0, 1.0))
    except BaseException:
        conn.close()
        raise


@contextlib.contextmanager
def granted_workers(
    pytest_args: Sequence[str],
    env: Mapping[str, str],
    stream: TextIO = sys.stderr,
) -> Iterator[Grant]:
    """Hold this run's share of the machine's workers for its duration."""
    request = requested_workers(pytest_args, env)
    if os.environ.get(HELD_ENV):
        yield Grant(None, request)
        return
    request, note = load_backoff(request)
    if note:
        print(note, file=stream, flush=True)
    conn, taken = _acquire(request, stream)
    prior = os.environ.get(HELD_ENV)
    # Published even when ungoverned, so a descendant never queues behind
    # the ancestor that cannot finish until it does.
    os.environ[HELD_ENV] = str(taken or 0)
    try:
        yield Grant(taken, request)
    finally:
        if prior is None:
            os.environ.pop(HELD_ENV, None)
        else:
            os.environ[HELD_ENV] = prior
        if conn is not None:
            conn.close()  # type: ignore[attr-defined]


__all__ = [
    "BUDGET_ENV",
    "BUDGET_MACHINE_CONFIG_KEY",
    "Grant",
    "HELD_ENV",
    "LOCK_BASE_ENV",
    "LOG_PREFIX",
    "WORKER_LOCK_BASE",
    "budget_size",
    "core_count",
    "granted_workers",
    "holders",
    "load_backoff",
    "requested_workers",
    "take_workers",
    "waiting_announcement",
]
