"""Path-integrity harness — invariant verifier for the path substrate.

The canonical path substrate provides Yoke's canonical path
registry, snapshot scanner, continuity recording, and durable path
context recording. This module is the proof harness that asks one
operator-level question:

    Can Yoke trust its project path map and attached path context
    enough for future path-integrity systems to make blocking decisions from it?

What the verifier asserts
-------------------------

For each registered project that has the required substrate, a verifier
run walks the recorded ``path_targets`` / ``path_snapshots`` /
``path_snapshot_entries`` / ``path_moves`` / ``path_context_values``
rows and asserts the invariants required for stable path identity,
continuity, and attached path context.
The check functions live in
:mod:`yoke_core.domain.path_integrity_invariants` and the run-side
bookkeeping (open / close / record-failure) lives in
:mod:`yoke_core.domain.path_integrity_runs`.

What the verifier does NOT do
-----------------------------

* It never reads live git state. Snapshot idempotency is asserted by
  comparing stored rows, not by re-running the scanner.
* It never blocks ``/yoke do`` / ``advance`` / ``conduct`` / ``usher``
  / ``charge``. Shadow-mode reporting only.
* It never claims path-target identity, never makes scheduler
  decisions, never rewrites repaired substrate without an explicit
  audited repair operation.

Lifecycle and recovery
----------------------

A verifier run opens a ``path_integrity_runs`` row in
``status='running'`` before any invariant runs. On clean completion it
transitions to ``passed`` (zero failures), ``failed`` (one or more
failures), or ``skipped`` / ``blocked`` (substrate or capability
gate). On the next ``verify`` invocation, any stale ``running`` row
owned by an aborted process is closed to ``status='aborted'`` with
``abort_reason='resumed_after_crash'`` before the new run opens.

Skip/block evidence
-------------------

Projects that the verifier cannot evaluate produce explicit rows.

* No registered project: ``status='skipped'``, ``skip_reason='no_project'``.
* Registered project with no snapshots: ``status='skipped'``,
  ``skip_reason='no_path_substrate'``.
* ``--commit`` request for a SHA with no recorded snapshot:
  ``status='skipped'``, ``skip_reason='no_head_snapshot'``.

Pass/fail dependency
--------------------

The :func:`has_green_run` helper is the only sanctioned blocking
consumer of integrity state. Downstream path-integrity consumers call it
to decide whether path-substrate truth is verified for a given
``(project_id, commit_sha)`` pair before relying on it.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_integrity_invariants import (
    ALL_INVARIANTS,
    INVARIANT_CONTEXT_INHERITANCE,
    INVARIANT_CONTINUITY_DETERMINISM,
    INVARIANT_DRIFT,
    INVARIANT_DUPLICATE_IDENTITY,
    INVARIANT_FUNCS,
    INVARIANT_PARENT_CHILD,
    INVARIANT_SNAPSHOT_IDEMPOTENCY,
)
from yoke_core.domain.path_integrity_runs import (
    ABORT_RESUMED_AFTER_CRASH,
    SKIP_NO_HEAD_SNAPSHOT,
    SKIP_NO_PROJECT,
    SKIP_NO_SUBSTRATE,
    STATUS_ABORTED,
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    VERIFIER_VERSION,
    close_run,
    close_stale_runs,
    open_run,
    record_failure,
)
from yoke_core.domain.project_identity import resolve_project, resolve_project_id


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_has_substrate(
    conn: Any, project_id: int
) -> bool:
    p = _p(conn)
    row = conn.execute(
        f"SELECT EXISTS(SELECT 1 FROM path_targets WHERE project_id={p})",
        (project_id,),
    ).fetchone()
    return bool(row[0])


def _all_registered_projects(
    conn: Any,
) -> List[int]:
    rows = conn.execute(
        "SELECT id FROM projects ORDER BY id"
    ).fetchall()
    return [int(r[0]) for r in rows]


def _resolve_target_snapshot_id(
    conn: Any,
    project_id: int,
    commit_sha: Optional[str],
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return (snapshot_id, commit_sha_used, skip_reason).

    When ``commit_sha`` is None, the verifier picks the most recent
    snapshot for the project. When it is provided, the verifier looks
    for that exact snapshot. Either branch can produce the
    ``no_head_snapshot`` skip reason.
    """
    p = _p(conn)
    if commit_sha is not None:
        row = conn.execute(
            "SELECT id FROM path_snapshots "
            f"WHERE project_id={p} AND commit_sha={p} "
            "ORDER BY id DESC LIMIT 1",
            (project_id, commit_sha),
        ).fetchone()
        if row is None:
            return None, commit_sha, SKIP_NO_HEAD_SNAPSHOT
        return int(row[0]), commit_sha, None
    row = conn.execute(
        "SELECT id, commit_sha FROM path_snapshots "
        f"WHERE project_id={p} ORDER BY id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None, None, SKIP_NO_HEAD_SNAPSHOT
    return int(row[0]), str(row[1]), None


def verify_project(
    conn: Any,
    project_id: int | str,
    *,
    commit_sha: Optional[str] = None,
) -> int:
    """Run the full invariant set against ``project_id``.

    Returns the ``path_integrity_runs.id`` row created. The returned
    row's ``status`` is one of ``passed`` / ``failed`` / ``skipped``
    when the function returns; the caller may inspect the row plus
    associated failures.

    The CLI exit code is derived elsewhere; this function is the
    in-process API.
    """
    ident = resolve_project(conn, project_id, required=False)
    resolved_project_id = ident.id if ident is not None else None
    close_stale_runs(conn, resolved_project_id)

    if resolved_project_id is None:
        run_id = open_run(
            conn, project_id=None, commit_sha=commit_sha,
        )
        close_run(
            conn, run_id=run_id, project_id=None,
            status=STATUS_SKIPPED, failure_count=0,
            unrepaired_failure_count=0, skip_reason=SKIP_NO_PROJECT,
            commit_sha=commit_sha,
        )
        return run_id
    project_id = resolved_project_id

    if not _project_has_substrate(conn, project_id):
        run_id = open_run(
            conn, project_id=project_id, commit_sha=commit_sha,
        )
        close_run(
            conn, run_id=run_id, project_id=project_id,
            status=STATUS_SKIPPED, failure_count=0,
            unrepaired_failure_count=0, skip_reason=SKIP_NO_SUBSTRATE,
            commit_sha=commit_sha,
        )
        return run_id

    snapshot_id, resolved_sha, skip_reason = _resolve_target_snapshot_id(
        conn, project_id, commit_sha,
    )
    if skip_reason is not None:
        run_id = open_run(
            conn, project_id=project_id, commit_sha=commit_sha,
        )
        close_run(
            conn, run_id=run_id, project_id=project_id,
            status=STATUS_SKIPPED, failure_count=0,
            unrepaired_failure_count=0, skip_reason=skip_reason,
            commit_sha=commit_sha,
        )
        return run_id

    run_id = open_run(
        conn, project_id=project_id, commit_sha=resolved_sha,
    )
    failure_count = 0
    for invariant_kind, fn in INVARIANT_FUNCS:
        for target_id, details in fn(conn, project_id):
            details = dict(details)
            details.setdefault("snapshot_id", snapshot_id)
            record_failure(
                conn, run_id=run_id, project_id=project_id,
                invariant_kind=invariant_kind,
                target_id=target_id, details=details,
            )
            failure_count += 1
    status = STATUS_PASSED if failure_count == 0 else STATUS_FAILED
    close_run(
        conn, run_id=run_id, project_id=project_id, status=status,
        failure_count=failure_count,
        unrepaired_failure_count=failure_count,
        commit_sha=resolved_sha,
    )
    return run_id


def verify_all_projects(
    conn: Any,
    *,
    commit_sha: Optional[str] = None,
) -> List[int]:
    """Run the verifier against every registered project.

    Projects without substrate or capabilities receive an explicit
    skip row (no silent fallback to ``yoke``). Returns the
    list of created ``path_integrity_runs`` IDs in project order.
    """
    close_stale_runs(conn, None)
    out: List[int] = []
    for project_id in _all_registered_projects(conn):
        out.append(verify_project(conn, project_id, commit_sha=commit_sha))
    return out


def has_green_run(
    conn: Any,
    project_id: int | str,
    commit_sha: str,
) -> bool:
    """Return True iff a passed verifier run exists for the pair.

    A "green run" is a ``path_integrity_runs`` row in
    ``status='passed'`` for ``(project_id, commit_sha)`` with zero
    unrepaired failures.

    This is the only sanctioned blocking consumer of integrity state.
    Downstream path-integrity consumers call it before relying
    on path substrate truth.
    """
    if not isinstance(project_id, int):
        project_id = resolve_project_id(conn, project_id)
    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM path_integrity_runs "
        f"WHERE project_id={p} AND commit_sha={p} AND status={p} "
        "  AND unrepaired_failure_count = 0 LIMIT 1",
        (project_id, commit_sha, STATUS_PASSED),
    ).fetchone()
    return row is not None


def main(argv: Optional[List[str]] = None) -> int:
    from yoke_core.domain.path_integrity_cli import main as _cli_main
    return _cli_main(argv)


__all__ = [
    "ABORT_RESUMED_AFTER_CRASH",
    "ALL_INVARIANTS",
    "INVARIANT_CONTEXT_INHERITANCE",
    "INVARIANT_CONTINUITY_DETERMINISM",
    "INVARIANT_DRIFT",
    "INVARIANT_DUPLICATE_IDENTITY",
    "INVARIANT_PARENT_CHILD",
    "INVARIANT_SNAPSHOT_IDEMPOTENCY",
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
    "has_green_run",
    "main",
    "verify_all_projects",
    "verify_project",
]


if __name__ == "__main__":
    raise SystemExit(main())
