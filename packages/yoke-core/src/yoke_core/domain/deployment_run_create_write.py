"""Allocate and insert deployment runs, each with its frozen membership.

Creation is one transaction on purpose: a retry's membership is part of the
row being created, not a follow-up write, and a release set's runs commit
together or not at all, so no refusal strands an earlier flow's run.
"""

from __future__ import annotations

from yoke_core.domain.domain_refusal import DomainRefusal

from typing import NamedTuple, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, utc_now
from yoke_core.domain.deployment_run_id_allocation import next_run_id, reserve_run_id
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


#: Serializes run creation against other creation for the same project only;
#: a table lock stalled every other write to ``deployment_runs`` and a deploy
#: driver's heartbeat timed out behind it, and one key for every project
#: queued unrelated releases behind each other. Composition's repository reads
#: happen before this lock (see :mod:`deployment_run_create_composition`), so
#: it covers database work.
_CREATE_LOCK_SQL = (
    "SELECT pg_advisory_xact_lock(hashtext('deployment_runs.create'), %s::int)"
)


class CreatedRun(NamedTuple):
    """The run a create returned, and how a keyed create identified it."""

    run_id: str
    replayed: bool
    #: ``None`` unkeyed; otherwise an ``idempotency.BASIS_*`` value.
    idempotency_basis: Optional[str]


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


def create_run(project: str, flow: str, **spec) -> CreatedRun:
    """Create a new deployment run, or return the one a keyed repeat names.

    *spec* takes :func:`create_run_set`'s per-flow keys plus ``db_path``. A
    keyed repeat with the same ``create_request`` returns the original run
    (``replayed=True``); a different request raises
    :class:`~yoke_core.domain.deployment_run_create_idempotency.IdempotencyKeyConflict`.
    ``environment`` overrides the flow's registered target.
    ``inherit_members_from`` copies a retry's frozen membership in the same
    transaction, so a retry is never committed member-less. A run waiting
    only on item QA on the same flow and target is taken over in that
    transaction (:mod:`~yoke_core.domain.deployment_run_target_takeover`);
    *session_id* and *actor_id* are the creator, audited on its removals.
    """
    db_path = spec.pop("db_path", None)
    return create_run_set(project, [{"flow": flow, **spec}], db_path=db_path)[0]


def create_run_set(
    project: str, specs: list[dict], *, db_path: Optional[str] = None
) -> list[CreatedRun]:
    """Create one run per spec, all or nothing, in one transaction.

    Each spec names ``flow`` and optionally ``environment``,
    ``release_lineage``, ``created_by``, ``artifact_identity``,
    ``inherit_members_from``, ``idempotency_key``, ``create_request``,
    ``allow_pending_pair_merges``, ``session_id`` and ``actor_id``. Every
    flow validates before the creation lock; under it each is replayed or
    created in order, with any takeover, and one commit ends the set. A
    refusal on any flow rolls back every run and takeover, so no key names
    a run that did not commit.
    """
    entries = [_entry(**spec) for spec in specs]
    return [created for created, _message in _create(project, db_path, entries)]


def _entry(
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    artifact_identity: Optional[str] = None,
    inherit_members_from: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    create_request: Optional[str] = None,
    allow_pending_pair_merges: bool = False,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> tuple[dict, dict]:
    run = {
        "flow": flow,
        "release_lineage": release_lineage,
        "created_by": created_by,
        "artifact_identity": artifact_identity,
        "inherit_members_from": inherit_members_from,
        "allow_pending_pair_merges": allow_pending_pair_merges,
        "session_id": session_id,
        "actor_id": actor_id,
        "enroll_item_id": None,
    }
    request = {
        "environment": environment,
        "idempotency_key": idempotency_key,
        "create_request": create_request,
    }
    return request, run


def create_item_run(
    project: str,
    flow: str,
    item_id: int,
    *,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    allow_pending_pair_merges: bool = False,
    session_id: Optional[str] = None,
) -> tuple[CreatedRun, str]:
    """Create a run with *item_id* enrolled, returning the validator's message.

    Creation, any takeover, the item's enrollment and composition validation
    with its item QA members share one transaction, so a refusal anywhere
    leaves no run, membership or takeover behind.
    """
    run = dict(
        flow=flow,
        release_lineage=release_lineage,
        created_by=created_by,
        artifact_identity=None,
        inherit_members_from=None,
        allow_pending_pair_merges=allow_pending_pair_merges,
        session_id=session_id,
        actor_id=None,
        enroll_item_id=int(item_id),
    )
    request = dict(environment=environment, idempotency_key=None, create_request=None)
    return _create(project, None, [(request, run)])[0]


def _create(
    project: str, db_path: Optional[str], entries: list[tuple[dict, dict]]
) -> list[tuple[CreatedRun, str]]:
    conn = connect(db_path)
    try:
        with composition_reads():
            results = _create_committed(conn, project, entries)
            for created, _message in results:
                if not created.replayed:
                    _finish_takeover(conn, created.run_id)
            return results
    finally:
        conn.close()


def _finish_takeover(conn, run_id: str) -> None:
    """Record a settled run's carried work once the creation has committed.

    This runs outside the locked validation scope: the settled run's own
    comparison was never a question of this creation, so it is read from the
    provider here rather than demanded from preparation, which would retry an
    already committed creation.
    """
    from yoke_core.domain.deployment_run_takeover_settlement import (
        finish_settled_takeover,
    )

    timed_preparation(
        "create_takeover_settlement", finish_settled_takeover, conn, run_id
    )


def _create_committed(
    conn, project: str, entries: list[tuple[dict, dict]]
) -> list[tuple[CreatedRun, str]]:
    if db_backend.connection_is_postgres(conn):
        for request, run in entries:
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
                    prepared_sources_only(
                        recovery=(
                            "Repeat the same deployment-runs create or start-for-item "
                            "command with its original arguments and idempotency key, "
                            "if supplied, to prepare current source facts."
                        )
                    ),
                ):
                    return _create_all_locked(conn, project, entries)
            except SourcePreparationChanged as exc:
                conn.rollback()
                if attempt == 7:
                    raise
                # Answer only the new exact source question with every
                # write lock released, then revalidate mutable facts.
                timed_preparation("create_source_refresh", exc.prepare)
    return _create_all_locked(conn, project, entries)


def _create_all_locked(
    conn, project: str, entries: list[tuple[dict, dict]]
) -> list[tuple[CreatedRun, str]]:
    """One transaction for every entry: one commit, or a rollback of all."""
    results = [_create_locked(conn, project, **request, **run) for request, run in entries]
    if all(created.replayed for created, _message in results):
        conn.rollback()
    else:
        timed_preparation("create_commit", conn.commit)
    return results


def _create_locked(
    conn,
    project: str,
    *,
    environment: Optional[str],
    idempotency_key: Optional[str],
    create_request: Optional[str],
    **run,
) -> tuple[CreatedRun, str]:
    """Replay, or allocate and insert, while holding the project's creation lock.

    The caller commits or rolls back; a set shares one transaction.
    Validation repeats here on the real row. Inside the caller's read scope
    the unlocked pass already resolved its repository reads, so this pass
    re-checks the database facts the lock protects.
    """
    project_id = resolve_project_id(conn, project)
    if db_backend.connection_is_postgres(conn):
        timed_preparation("create_lock", conn.execute, _CREATE_LOCK_SQL, (project_id,))
    basis = idempotency.BASIS_RECORDED_KEY if idempotency_key else None
    if basis == idempotency.BASIS_RECORDED_KEY:
        existing = idempotency.existing_run(
            conn, project_id, idempotency_key, create_request
        )
        if existing is not None:
            return CreatedRun(existing, True, basis), ""
        idempotency.release_unstarted_key(conn, project_id, idempotency_key)
    target = run_target(conn, run["flow"], project_id, environment)

    refuse_run_that_cannot_execute(conn, run["flow"], run["release_lineage"])

    # Allocation and insertion share this transaction. The standalone
    # next-id command remains a non-reserving preview.
    now = utc_now()
    run_id = (
        reserve_run_id(conn, now)
        if db_backend.connection_is_postgres(conn)
        else next_run_id(conn, now)
    )
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
    return CreatedRun(run_id, False, basis), message


__all__ = [
    "CompositionRefused",
    "CreatedRun",
    "cmd_create_run",
    "create_item_run",
    "create_run",
    "create_run_set",
]
