"""Path-integrity run-lifecycle helpers.

Owns the writer-side bookkeeping for ``path_integrity_runs`` and
``path_integrity_failures`` rows plus the canonical event emissions.
The driver in :mod:`yoke_core.domain.path_integrity` calls these
helpers; tests assert their behavior against synthetic substrate.

Status vocabulary (also stored in the ``status`` column):

* ``running`` — opened, not yet completed.
* ``passed`` — closed with zero failures.
* ``failed`` — closed with one or more failures.
* ``skipped`` — substrate or capability gate prevented the run.
* ``blocked`` — verifier could not run because the substrate is in a
  state that makes assertion meaningless.
* ``aborted`` — closed-out stale ``running`` row from a prior crash.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.events import emit_event


VERIFIER_VERSION = "v1"

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
# STATUS_BLOCKED is a path-integrity-runs status (the
# verifier could not assert), unrelated to items.blocked or to
# path_claims.state='blocked'. Each "blocked" lives in its own domain.
STATUS_BLOCKED = "blocked"
STATUS_ABORTED = "aborted"

SKIP_NO_PROJECT = "no_project"
SKIP_NO_SUBSTRATE = "no_path_substrate"
SKIP_NO_HEAD_SNAPSHOT = "no_head_snapshot"

ABORT_RESUMED_AFTER_CRASH = "resumed_after_crash"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def close_stale_runs(
    conn: Any, project_id: Optional[int]
) -> int:
    """Close any ``running`` rows from prior crashed verifier processes.

    When ``project_id`` is None, sweeps every project; otherwise
    only the named project's stale rows are closed.
    """
    p = _p(conn)
    if project_id is None:
        cur = conn.execute(
            "UPDATE path_integrity_runs "
            f"SET status={p}, completed_at={p}, abort_reason={p} "
            f"WHERE status={p}",
            (STATUS_ABORTED, iso8601_now(), ABORT_RESUMED_AFTER_CRASH,
             STATUS_RUNNING),
        )
    else:
        cur = conn.execute(
            "UPDATE path_integrity_runs "
            f"SET status={p}, completed_at={p}, abort_reason={p} "
            f"WHERE status={p} AND project_id={p}",
            (STATUS_ABORTED, iso8601_now(), ABORT_RESUMED_AFTER_CRASH,
             STATUS_RUNNING, project_id),
        )
    conn.commit()
    return int(cur.rowcount)


def open_run(
    conn: Any,
    *,
    project_id: Optional[int],
    commit_sha: Optional[str],
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_integrity_runs "
        "(project_id, commit_sha, status, started_at, "
        " verifier_version) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id",
        (project_id, commit_sha, STATUS_RUNNING, iso8601_now(),
         VERIFIER_VERSION),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()
    emit_event(
        "PathIntegrityRunStarted",
        event_kind="lifecycle",
        event_type="path_integrity",
        source_type="backend",
        project=project_id,
        outcome="started",
        context={
            "project_id": project_id,
            "run_id": run_id,
            "commit_sha": commit_sha,
            "verifier_version": VERIFIER_VERSION,
        },
        conn=conn,
    )
    return run_id


def close_run(
    conn: Any,
    *,
    run_id: int,
    project_id: Optional[int],
    status: str,
    failure_count: int,
    unrepaired_failure_count: int,
    skip_reason: Optional[str] = None,
    block_reason: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> None:
    p = _p(conn)
    conn.execute(
        "UPDATE path_integrity_runs "
        f"SET status={p}, completed_at={p}, failure_count={p}, "
        f"    unrepaired_failure_count={p}, skip_reason={p}, block_reason={p} "
        f"WHERE id={p}",
        (status, iso8601_now(), failure_count,
         unrepaired_failure_count, skip_reason, block_reason, run_id),
    )
    conn.commit()
    emit_event(
        "PathIntegrityRunCompleted",
        event_kind="lifecycle",
        event_type="path_integrity",
        source_type="backend",
        project=project_id,
        outcome=status,
        severity="WARN" if status == STATUS_FAILED else "INFO",
        context={
            "project_id": project_id,
            "run_id": run_id,
            "commit_sha": commit_sha,
            "status": status,
            "failure_count": failure_count,
            "unrepaired_failure_count": unrepaired_failure_count,
            "skip_reason": skip_reason,
            "block_reason": block_reason,
            "verifier_version": VERIFIER_VERSION,
        },
        conn=conn,
    )


def record_failure(
    conn: Any,
    *,
    run_id: int,
    project_id: int,
    invariant_kind: str,
    target_id: Optional[int],
    details: dict,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_integrity_failures "
        "(run_id, invariant_kind, target_id, details, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id",
        (run_id, invariant_kind, target_id,
         json.dumps(details, sort_keys=True), iso8601_now()),
    )
    failure_id = int(cur.fetchone()[0])
    conn.commit()
    emit_event(
        "PathIntegrityFailureDetected",
        event_kind="lifecycle",
        event_type="path_integrity",
        source_type="backend",
        project=project_id,
        severity="WARN",
        outcome="failed",
        context={
            "project_id": project_id,
            "run_id": run_id,
            "failure_id": failure_id,
            "invariant_kind": invariant_kind,
            "target_id": target_id,
            "details": details,
        },
        conn=conn,
    )
    return failure_id


__all__ = [
    "ABORT_RESUMED_AFTER_CRASH",
    "SKIP_NO_HEAD_SNAPSHOT",
    "SKIP_NO_PROJECT",
    "SKIP_NO_SUBSTRATE",
    "STATUS_ABORTED",
    "STATUS_BLOCKED",
    "STATUS_FAILED",
    "STATUS_PASSED",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "VERIFIER_VERSION",
    "close_run",
    "close_stale_runs",
    "open_run",
    "record_failure",
]
