"""Allocate and insert one deployment run, with its frozen membership.

Creation is a single transaction on purpose. A retry is the same candidate for
the same items, so its membership is part of the row being created rather than
a follow-up write: committing the run first would leave a member-less retry
behind any copy failure, and a member-less item-bound run can never reach its
own completion gate — which is the defect the retry path exists to remove.
"""

from __future__ import annotations

from yoke_core.domain.domain_refusal import DomainRefusal

import re
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, utc_now
from yoke_core.domain import deployment_run_create_idempotency as idempotency
from yoke_core.domain.deployment_run_create_composition import (
    compose_run,
    refuse_run_that_cannot_execute,
    run_target,
    validate_before_lock,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.schema_read_scope import composition_reads
from yoke_core.domain.deployment_source_reads import (
    prepared_sources_only,
    SourcePreparationChanged,
)
from yoke_core.domain.deployment_runs_lock import bounded_run_write
from yoke_core.domain.deployment_start_timing import timed_preparation, timing_facts


class CompositionRefused(DomainRefusal, ValueError):
    """The composition validator answered no, so the run row was rolled back.

    A caller that only wants to know whether the release surfaces can read and
    judge a database needs to tell this verdict apart from a driver that broke
    reaching it. Matching the refusal text would couple that caller to a
    message the validator owns, so the distinction is carried by the type.
    ``ValueError`` stays the base class because a refused composition is still
    the bad-argument answer every existing caller already handles.
    """


#: Serializes run creation against other creation only; a table lock stalled
#: every other write to ``deployment_runs`` and a deploy driver's heartbeat
#: timed out behind it. Composition's repository reads happen before this lock
#: (see :mod:`deployment_run_create_composition`), so it covers database work.
_CREATE_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('deployment_runs.create'))"


class CreatedRun(NamedTuple):
    """The run a create returned, and how a keyed create identified it."""

    run_id: str
    replayed: bool
    #: ``None`` unkeyed; otherwise an ``idempotency.BASIS_*`` value.
    idempotency_basis: Optional[str]


def cmd_next_id(db_path: Optional[str] = None) -> str:
    """Preview the next run ID for today without reserving it."""
    conn = connect(db_path)
    try:
        return _next_run_id(conn, utc_now())
    finally:
        conn.close()


def _next_run_id(conn, now: datetime) -> str:
    """Return max numeric suffix + 1 for *now*'s UTC day."""
    today = now.astimezone(timezone.utc).strftime("%Y%m%d")
    prefix = f"run-{today}-"
    rows = conn.execute(
        "SELECT id FROM deployment_runs WHERE id LIKE %s",
        (f"{prefix}%",),
    ).fetchall()
    pattern = re.compile(rf"^{re.escape(prefix)}([0-9]+)$")
    suffixes = [
        int(match.group(1))
        for row in rows
        if (match := pattern.fullmatch(str(row[0]))) is not None
    ]
    return f"{prefix}{max(suffixes, default=0) + 1:03d}"


def cmd_create_run(
    project: str,
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    artifact_identity: Optional[str] = None,
    db_path: Optional[str] = None,
    inherit_members_from: Optional[str] = None,
    allow_pending_pair_merges: bool = False,
    session_id: Optional[str] = None,
) -> str:
    """Create a new deployment run without a caller key. Returns its ID.

    An explicit commit is refused when the flow's CI gate could never pass
    it; a run created without one binds its commit later, where
    :func:`~yoke_core.domain.deployment_run_lineage_rebind.refuse_lineage_write`
    applies the same refusal.
    """
    from yoke_core.domain.deployment_run_ci_tested_source import (
        require_tested_lineage,
    )

    require_tested_lineage(project, flow, environment, release_lineage)
    created = create_run(
        project,
        flow,
        environment=environment,
        release_lineage=release_lineage,
        created_by=created_by,
        artifact_identity=artifact_identity,
        db_path=db_path,
        inherit_members_from=inherit_members_from,
        allow_pending_pair_merges=allow_pending_pair_merges,
        session_id=session_id,
    )
    return created.run_id


def create_run(
    project: str,
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    artifact_identity: Optional[str] = None,
    db_path: Optional[str] = None,
    inherit_members_from: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    create_request: Optional[str] = None,
    allow_pending_pair_merges: bool = False,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> CreatedRun:
    """Create a new deployment run, or return the one a keyed repeat names.

    ``idempotency_key`` with its canonical ``create_request`` makes the create
    safe to repeat: under the creation lock, a run already created with that key
    and request is returned with ``replayed=True`` instead of minting another,
    and the same key with a different request raises
    :class:`~yoke_core.domain.deployment_run_create_idempotency.IdempotencyKeyConflict`.
    Before the key columns converge, the key cannot be stored; the same lock
    instead returns the one never-started run with the identical resolved
    request, and the result names that basis.

    ``environment`` (a registered name) overrides the flow's registered
    target; tier and environment otherwise copy from the flow definition.

    ``inherit_members_from`` copies that run's frozen membership onto the new
    run inside this same transaction. A retry is the same candidate for the
    same items, so the two facts are one write: committing the run first would
    leave a member-less retry behind any copy failure, and a member-less
    item-bound retry is precisely what cannot reach its completion gate.

    An executing run on the same flow and target that waits only on item QA
    is taken over in this same transaction
    (:mod:`~yoke_core.domain.deployment_run_target_takeover`); *session_id*
    and *actor_id* are the creator, audited on that run's removals.
    """
    run = {
        "flow": flow,
        "release_lineage": release_lineage,
        "created_by": created_by,
        "artifact_identity": artifact_identity,
        "inherit_members_from": inherit_members_from,
        "allow_pending_pair_merges": allow_pending_pair_merges,
        "session_id": session_id,
        "actor_id": actor_id,
    }
    request = {
        "environment": environment,
        "idempotency_key": idempotency_key,
        "create_request": create_request,
    }
    conn = connect(db_path)
    try:
        with composition_reads():
            if db_backend.connection_is_postgres(conn):
                timed_preparation(
                    "create_provisional_composition",
                    validate_before_lock,
                    conn,
                    project,
                    **request,
                    **run,
                )
                for attempt in range(8):
                    try:
                        with (
                            bounded_run_write(conn, "new release"),
                            prepared_sources_only(),
                        ):
                            timed_preparation(
                                "create_lock", conn.execute, _CREATE_LOCK_SQL
                            )
                            return _create_locked(conn, project, **request, **run)
                    except SourcePreparationChanged as exc:
                        conn.rollback()
                        if attempt == 7:
                            raise
                        # Answer only the new exact source question with every
                        # write lock released, then revalidate mutable facts.
                        timed_preparation("create_source_refresh", exc.prepare)
            return _create_locked(conn, project, **request, **run)
    finally:
        conn.close()


def _create_locked(
    conn,
    project: str,
    *,
    environment: Optional[str],
    idempotency_key: Optional[str],
    create_request: Optional[str],
    **run,
) -> CreatedRun:
    """Replay, or allocate and insert, while holding the creation lock.

    Validation repeats here on the real row. Inside the caller's read scope
    the unlocked pass already resolved its repository reads, so this pass
    re-checks the database facts the lock protects.
    """
    project_id = resolve_project_id(conn, project)
    basis = idempotency.BASIS_RECORDED_KEY if idempotency_key else None
    if basis == idempotency.BASIS_RECORDED_KEY:
        existing = idempotency.existing_run(
            conn, project_id, idempotency_key, create_request
        )
        if existing is not None:
            conn.rollback()
            return CreatedRun(existing, True, basis)
    target = run_target(conn, run["flow"], project_id, environment)

    refuse_run_that_cannot_execute(conn, run["flow"], run["release_lineage"])

    # Allocation and insertion share this serialized transaction. The
    # standalone next-id command remains a non-reserving preview.
    now = utc_now()
    run_id = _next_run_id(conn, now)
    timing_facts(run_id=run_id, source_sha=run["release_lineage"] or "")
    keyed = basis == idempotency.BASIS_RECORDED_KEY
    valid, message = timed_preparation(
        "create_locked_composition",
        compose_run,
        conn,
        run_id,
        created_at=now,
        project_id=project_id,
        target=target,
        create_idempotency_key=idempotency_key if keyed else None,
        create_request=create_request if keyed else None,
        **run,
    )
    if not valid:
        raise CompositionRefused(message)
    timed_preparation("create_commit", conn.commit)
    timed_preparation(
        "create_takeover_settlement", _finish_superseded_run, conn, run_id
    )
    return CreatedRun(run_id, False, basis)


def _finish_superseded_run(conn, run_id: str) -> None:
    """Let a taken-over run that kept its passed members complete now.

    Its takeover already committed; completion is the run's own ordinary
    close-out, which reports its own recovery when it cannot finish yet.
    """
    from yoke_core.domain.deployment_run_target_takeover import (
        SUPERSEDES_COLUMN,
        takeover_available,
    )

    if not takeover_available(conn):
        return
    row = conn.execute(
        f"SELECT old.id FROM deployment_runs new JOIN deployment_runs old "
        f"ON old.id = new.{SUPERSEDES_COLUMN} "
        "WHERE new.id = %s AND old.status = 'executing'",
        (run_id,),
    ).fetchone()
    if row is None:
        return
    from yoke_core.domain.deployment_run_auto_completion import (
        continue_after_settlement,
    )

    continue_after_settlement(conn, str(row[0]))


__all__ = [
    "CompositionRefused",
    "CreatedRun",
    "cmd_create_run",
    "cmd_next_id",
    "create_run",
]
