"""Apply the pending migration history to a database, in order, at boot.

This is the whole distribution mechanism. A container starting on new code
brings its own database up to that code before it serves, so "deployed" and
"migrated" stop being two things that can disagree. There is no per-target
dispatch or operator apply: the wheel carries the history, and boot carries
the apply. Release manifests independently attest which permanent bytes that
wheel contains; boot does not use them as a dispatch list.

The kernel is deliberately ignorant of *whose* history it applies — the
caller passes one. That keeps the "should this run here?" judgment with the
caller that knows the answer, and lets a second install family (a registry
database with its own history) reuse this code rather than copy it.

Postgres transactional DDL commits an entry's ``apply()`` with its ledger row,
so "applied but unrecorded" has no window in which to exist. A failed entry
stops the chain: boot is fail-hard rather than serving behind its own schema.

Full rationale: ``docs/archive/decisions/ordered-cumulative-migrations.md``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from yoke_core.domain import (
    db_backend,
    migration_restore_point,
    migration_serving_version,
)
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_boot_ledger import (
    applied_names,
    pending_entries,
    record_applied,
)
from yoke_core.domain.migration_content_identity import (
    raw_content_sha256,
    require_matching_content_identity,
)
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_audit_receipts import now_stamp, write_receipt


class EntryFailed(MigrationApplyError):
    """An entry that could not be applied, named by what actually broke.

    An entry rarely reports its own failure accurately. Most wrap their SQL in
    ``try``/``finally`` to restore a guard they crossed, and on Postgres the
    statement that really failed aborts the transaction — so the cleanup in
    the ``finally`` fails too, with a generic "transaction is aborted", and
    that replaces the real error. The original survives only on
    ``__context__``, which no log surface prints and which the reports
    reaching an operator routinely truncate away. Carrying the root cause in
    this message keeps it legible down to a single final line.
    """


def _root_cause(exc: BaseException) -> BaseException:
    """The deepest exception behind this one, following causes and contexts."""
    seen = {id(exc)}
    root = exc
    while True:
        deeper = root.__cause__ or root.__context__
        if deeper is None or id(deeper) in seen:
            return root
        seen.add(id(deeper))
        root = deeper


def _failure_reason(exc: BaseException) -> str:
    root = _root_cause(exc)
    if root is exc:
        return f"{type(exc).__name__}: {exc}"
    return f"{type(root).__name__}: {root} (surfaced as {type(exc).__name__})"


#: Advisory-lock id serializing migration apply on one database. Postgres
#: advisory locks already carry the database in their lock tag, so a single
#: constant gives per-database exclusion for free: two servers rolling the
#: same tenant contend, while different tenants never do. Derived from a
#: name so it is stable and self-documenting rather than a bare magic number.
MIGRATION_APPLY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"yoke.migration.boot_apply").digest()[:8],
    "big",
    signed=True,
)


@dataclass(frozen=True)
class ApplyOutcome:
    """What one ``apply_pending`` call did."""

    applied: Tuple[str, ...]
    restore_point: Optional[str]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def stamp_history(
    conn: Any,
    history: Sequence[MigrationEntry],
    *,
    ledger: LedgerContract,
    applied_by: str,
) -> Tuple[str, ...]:
    """Record the whole history as applied without running any of it.

    For a database that was just born: its schema came from the current code,
    so every historical entry is already true of it by construction and
    running them would be at best a no-op and at worst a corruption. The
    equivalent of Flyway's baseline or Django's fake-initial.

    Birth is a fact the caller observes, never something inferred from an
    empty ledger here — a pre-ledger database that predates this mechanism
    also has no rows, and stamping *that* one would skip real work.
    """
    require_matching_content_identity(conn, history, ledger)
    stamped: list[str] = []
    try:
        for entry in history:
            source_bytes = entry.path.read_bytes()
            module = load_migration_module(
                entry.path,
                entry.name,
                source_bytes=source_bytes,
                check_psycopg_sql=db_backend.connection_is_postgres(conn),
            )
            if entry.path.read_bytes() != source_bytes:
                raise EntryFailed(
                    f"{entry.name} source changed while birth evidence was captured"
                )
            record_applied(
                conn,
                entry,
                ledger=ledger,
                applied_by=applied_by,
                content_sha256=raw_content_sha256(source_bytes),
                minimum_serving_version=(
                    migration_serving_version.declared_minimum(module)
                ),
            )
            stamped.append(entry.name)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tuple(stamped)


def apply_pending(
    conn: Any,
    *,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
    applied_by: str,
    running_version: str,
    backup_root: Optional[Path] = None,
    backup_target_dsn: Optional[str] = None,
    external_restore_point: Optional[str] = None,
) -> ApplyOutcome:
    """Apply every entry this database still owes, oldest first.

    Exactly one restore-point source must be supplied. ``backup_root`` plus a
    caller-resolved ``backup_target_dsn`` makes the kernel take a ``pg_dump``
    itself, which is right where the database is local to the machine or its
    volume. ``external_restore_point`` names a
    restore point someone else established — the managed-Postgres snapshot a
    fleet roll takes before replacing any container, which is both faster than
    a per-database dump and, unlike one written inside a container about to be
    torn down, still there afterwards.

    Refusing when neither is present is the policy, not a precaution: nothing
    destructive runs without a named way back.

    ``running_version`` is the version of the artifact doing the applying. The
    kernel stays ignorant of what that means — the caller knows whether it is
    a wheel version, an image tag, or nothing at all — and an empty string is
    the honest answer from a source tree. It is required rather than defaulted
    on purpose: an omitted version reads as unresolved and disables the
    refusal entirely, so a default would let a caller silently switch the
    guard off. Passing ``""`` is still allowed, but it has to be said. It is compared against each entry's
    declared floor, so an entry can never be applied by a build too old to
    serve against the result, and it is recorded on the ledger row, because a
    build old enough to be in danger does not ship the entry that would tell
    it so.
    """
    if not history:
        return ApplyOutcome(applied=(), restore_point=None)

    # A permanent name whose recorded non-NULL digest differs is corruption,
    # not pending work. Refuse before the current fast-path or any restore.
    require_matching_content_identity(conn, history, ledger)

    # Cheap probe first. The overwhelming majority of boots are current, and
    # they should cost two queries and take no lock at all.
    if not pending_entries(conn, history, ledger):
        return ApplyOutcome(applied=(), restore_point=None)

    restore_point = migration_restore_point.establish(
        conn,
        backup_root=backup_root,
        backup_target_dsn=backup_target_dsn,
        external_restore_point=external_restore_point,
    )

    _acquire_apply_lock(conn)
    try:
        # Re-enumerate under the lock. Reading the pending set before taking
        # it is check-then-act: the boot guard other containers hold is a
        # *shared* lock, so two of them genuinely do converge at once, and
        # both would otherwise see the same work and race to do it.
        require_matching_content_identity(conn, history, ledger)
        outstanding = pending_entries(conn, history, ledger)
        applied: list[str] = []
        for entry in outstanding:
            _apply_one(
                conn,
                entry,
                ledger=ledger,
                applied_by=applied_by,
                running_version=running_version,
                restore_point=restore_point,
            )
            applied.append(entry.name)
        return ApplyOutcome(applied=tuple(applied), restore_point=restore_point)
    finally:
        _release_apply_lock(conn)


def _apply_one(
    conn: Any,
    entry: MigrationEntry,
    *,
    ledger: LedgerContract,
    applied_by: str,
    running_version: str,
    restore_point: str,
) -> None:
    source_bytes = entry.path.read_bytes()
    source_sha256 = raw_content_sha256(source_bytes)
    module = load_migration_module(
        entry.path,
        entry.name,
        source_bytes=source_bytes,
        check_psycopg_sql=db_backend.connection_is_postgres(conn),
    )
    if entry.path.read_bytes() != source_bytes:
        raise EntryFailed(
            f"{entry.name} source changed while the migration module loaded"
        )
    minimum = migration_serving_version.declared_minimum(module)
    # Refuse before DDL: a newer floor means the declaration and code disagree.
    # Catching it here costs nothing; catching it later costs the database.
    migration_serving_version.refuse_if_behind(entry.name, running_version, minimum)
    started_at = now_stamp()
    failure_state = "live_apply_failed"
    failure_phase = "apply"
    try:
        # apply() and the ledger row land together or not at all. The module
        # contract forbids committing inside apply() for exactly this reason.
        module.apply(conn)
        failure_state = "live_verify_failed"
        failure_phase = "source verification"
        if entry.path.read_bytes() != source_bytes:
            raise MigrationApplyError(
                f"{entry.name} source changed while apply executed"
            )
        failure_state = "live_apply_failed"
        failure_phase = "ledger write"
        record_applied(
            conn,
            entry,
            ledger=ledger,
            applied_by=applied_by,
            content_sha256=source_sha256,
            minimum_serving_version=minimum,
        )
        invariants = getattr(module, "invariants", None)
        if callable(invariants):
            # Verification belongs to the same transaction as mutation and
            # membership. Recording an entry before its invariants pass makes
            # a failed migration look current on the next boot and prevents
            # the retry that could repair it.
            failure_state = "live_verify_failed"
            failure_phase = "invariants"
            invariants(conn)
        failure_state = "live_verify_failed"
        failure_phase = "source verification"
        if entry.path.read_bytes() != source_bytes:
            raise MigrationApplyError(
                f"{entry.name} source changed before migration commit"
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — receipt, then fail the boot
        conn.rollback()
        reason = _failure_reason(exc)
        write_receipt(
            conn,
            entry,
            state=failure_state,
            started_at=started_at,
            completed_at=now_stamp(),
            restore_point=restore_point,
            failure_reason=reason[:500],
        )
        raise EntryFailed(f"{entry.name} {failure_phase} failed -- {reason}") from exc

    write_receipt(
        conn,
        entry,
        state="completed",
        started_at=started_at,
        completed_at=now_stamp(),
        restore_point=restore_point,
    )


def _acquire_apply_lock(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_APPLY_LOCK_KEY,))


def _release_apply_lock(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_APPLY_LOCK_KEY,))
    except Exception:  # noqa: BLE001 — the session ending releases it anyway
        pass


__all__ = [
    "ApplyOutcome",
    "EntryFailed",
    "MIGRATION_APPLY_LOCK_KEY",
    "applied_names",
    "apply_pending",
    "pending_entries",
    "stamp_history",
]
