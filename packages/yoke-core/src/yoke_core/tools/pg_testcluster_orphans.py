"""Reclaiming test databases whose owning invocation has exited.

Split from the cluster frontend so each file stays within the authored-file
line limit. The frontend owns the cluster's lifecycle; this module owns the
one question that outlives any single run — which databases are nobody's
any more, and how to reclaim them without ever delaying a starting suite.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import sys
import time

from yoke_core.domain import pg_test_db_namespace


def _frontend():
    """Return the cluster frontend, imported at call time.

    The frontend dispatches to this module and this module calls back into
    its cluster primitives, so the import cannot happen at module scope.
    Resolving it per call also keeps test patches on the frontend effective.
    """
    from yoke_core.tools import pg_testcluster

    return pg_testcluster

#: Imported lazily inside each entry point: the frontend owns the cluster
#: primitives this module calls, and it in turn dispatches to this module,
#: so neither can import the other at module scope.


# A database is reclaimable only once its owning invocation is gone, and the
# owner check alone would be unsafe: operating systems recycle PIDs, so a dead
# owner's PID can be reused by an unrelated live process. Requiring the
# database to ALSO be older than this makes a misread PID harmless. Erring
# long is free: anything missed is reclaimed by the next sweep.
ORPHAN_TEST_DB_MIN_AGE_MINUTES = 15

#: Age is read from ``PG_VERSION``, which PostgreSQL writes once when it
#: creates a database and never rewrites, so it is a true creation timestamp.
#: The database DIRECTORY's timestamp is not: the checkpointer and autovacuum
#: touch it for their own reasons, so an abandoned database keeps looking
#: freshly used and never becomes eligible. Measured against this cluster, the
#: directory signal made 0 of 161 known-dead databases reclaimable while the
#: creation signal correctly identified 138 — which is how a cluster silently
#: reaches hundreds of leaked databases and gigabytes of disk.
_DATABASE_CREATION_STAMP = "'base/' || d.oid::text || '/PG_VERSION'"

#: Ceiling on a single drop. ``DROP DATABASE`` unlinks a directory tree, so on
#: a machine already saturated by several suites it legitimately takes seconds;
#: too tight a bound turns every attempt into a failure that re-queues the same
#: database forever. The sweep no longer blocks anything, so it can afford to
#: wait — this exists only to abandon a genuinely wedged database.
ORPHAN_DROP_STATEMENT_TIMEOUT_MS = 30_000

#: Total wall-clock one sweep may spend dropping before leaving the rest for
#: the next one, so a large backlog drains over several runs instead of one
#: process grinding through hundreds of databases.
ORPHAN_SWEEP_TIME_BUDGET_SECONDS = 60.0

#: Name of the lock file that keeps the sweep single-flight across processes.
#: Concurrent sweeps are worse than no sweep: every invocation would target the
#: same backlog, and they would spend their budgets colliding on the same
#: DROP locks instead of reclaiming anything.
_SWEEP_LOCK_FILENAME = "orphan-sweep.lock"


@contextlib.contextmanager
def _single_sweeper():
    """Yield true only to the one process currently allowed to sweep.

    Every invocation on the machine shares one cluster root, so a lock file
    there is the natural mutex. The lock is taken non-blocking: a run that
    finds a sweep already underway skips instantly rather than queueing, which
    is the whole point — startup must never wait on cleanup.
    """
    root = _frontend()._root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / _SWEEP_LOCK_FILENAME).open("w")
    except OSError:
        yield True  # Cannot lock; sweeping unguarded beats not sweeping.
        return
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _owner_process_is_alive(pid: int) -> bool:
    """Return true when *pid* names a live process.

    ``PermissionError`` means the process exists but belongs to another user —
    still alive, and still not ours to reclaim.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True  # Unreadable means "assume live"; the sweep is optional.
    return True


def sweep_orphaned_test_databases() -> int:
    """Reclaim owner-tagged test databases whose owning invocation is gone.

    Every database an invocation creates carries that invocation's run tag, so
    the sweep can ask the operating system a definite question — is the owner
    still running? — instead of guessing from connection counts and mtimes.
    Databases belonging to live invocations are never touched, which is what
    makes this safe to run while other suites are mid-flight.

    Databases whose names carry no run tag are outside the namespace entirely
    (an operator's migration validation database, for instance) and are never
    candidates. Individual drop failures are reported and skipped rather than
    aborting the sweep: cleanup is best-effort, and a concurrent sweep that
    already reclaimed the same database must not fail this one.

    The sweep is single-flight and time-budgeted because it runs just before a
    suite starts. Left unbounded it becomes the stall it exists to prevent: a
    backlog of hundreds of orphans, swept by every concurrent invocation at
    once, means each one spends minutes colliding on the same DROP locks
    before pytest can even collect. One sweeper, a bounded slice of work, and
    the remainder left for next time.
    """
    if not _frontend()._is_ready():
        return 0
    with _single_sweeper() as may_sweep:
        if not may_sweep:
            return 0
        return _reclaim_orphans()


def _reclaim_orphans() -> int:
    res = _frontend()._psql(
        "SELECT datname FROM pg_database d "
        f"WHERE datname LIKE '{pg_test_db_namespace.OWNED_DATABASE_LIKE_PATTERN}' "
        f"AND (pg_stat_file({_DATABASE_CREATION_STAMP}, true)).modification "
        f"  < now() - interval '{ORPHAN_TEST_DB_MIN_AGE_MINUTES} minutes' "
        "ORDER BY datname"
    )
    if res.returncode != 0:
        # Most likely the cluster role cannot read server files. Decline the
        # sweep loudly rather than reclaiming on the PID check alone.
        sys.stderr.write(res.stdout + res.stderr)
        sys.stderr.write(
            "pg_testcluster: cannot determine test-database age; skipping "
            "orphan sweep rather than risk reclaiming a live run's database\n"
        )
        return 0
    reclaimed = 0
    remaining = 0
    deadline = time.monotonic() + ORPHAN_SWEEP_TIME_BUDGET_SECONDS
    for name in [line for line in res.stdout.splitlines() if line]:
        owner_pid = pg_test_db_namespace.owner_pid_of(name)
        if owner_pid is None or _owner_process_is_alive(owner_pid):
            continue
        if time.monotonic() >= deadline:
            remaining += 1
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        # FORCE terminates whatever the dead owner left connected — a leaked
        # child process is exactly how a database outlives its invocation.
        drop = _frontend()._psql(
            f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)",
            statement_timeout_ms=ORPHAN_DROP_STATEMENT_TIMEOUT_MS,
        )
        if drop.returncode != 0:
            sys.stderr.write(drop.stdout + drop.stderr)
            continue
        reclaimed += 1
    # Say so when there was anything to reclaim. A silent sweep let this
    # cluster reach 275 leaked databases and 12G unnoticed, because the only
    # visible symptom was a suite that got slower and slower. Naming what was
    # deferred matters just as much: a backlog draining a slice per run should
    # look deliberate, not like cleanup that stopped working.
    if reclaimed or remaining:
        deferred = f"; {remaining} left for the next sweep" if remaining else ""
        sys.stderr.write(
            f"pg_testcluster: reclaimed {reclaimed} orphaned test database(s) "
            f"from interrupted runs{deferred}\n"
        )
    return 0


def start_detached_orphan_sweep() -> None:
    """Kick off an orphan sweep that outlives this call and blocks nothing.

    Cleanup must never sit in a suite's critical path. Dropping a database is
    seconds of disk work on a loaded machine, and a backlog of hundreds of them
    swept synchronously means every run waits minutes before pytest can even
    collect — the precise stall this cleanup exists to prevent. Detaching it
    keeps startup at roughly zero cost while the backlog still drains; the
    sweep's own file lock keeps repeated launches from piling up.
    """
    try:
        subprocess.Popen(
            # The frontend owns the command-line entry point; this module has
            # none, and a spawn naming it would die instantly on a missing
            # __main__ — silently, since the streams below are discarded.
            [sys.executable, "-m", "yoke_core.tools.pg_testcluster", "prune"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass  # Cleanup is best-effort; never fail a run over it.
