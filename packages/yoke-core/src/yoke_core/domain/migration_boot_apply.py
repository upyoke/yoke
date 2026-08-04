"""Apply the pending migration history to a database, in order, at boot.

This is the whole distribution mechanism. A container starting on new code
brings its own database up to that code before it serves, so "deployed" and
"migrated" stop being two things that can disagree. There is no dispatch, no
manifest, and no operator step: the wheel carries the history, the boot
carries the apply.

The kernel is deliberately ignorant of *whose* history it applies — the
caller passes one. That keeps the "should this run here?" judgment with the
caller that knows the answer, and lets a second install family (a registry
database with its own history) reuse this code rather than copy it.

Two properties are the reason to prefer this shape over the mechanism it
replaced. *Applied and recorded are one transaction*: Postgres has
transactional DDL, so an entry's ``apply()`` and its ledger row commit
together, and the "applied but unrecorded" state other migration tools ship
repair tooling for has no window in which to exist. *A failed entry stops the
chain*: boot is fail-hard, because serving behind your own schema is the
failure this exists to prevent.

Full rationale: ``docs/archive/decisions/ordered-cumulative-migrations.md``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Set, Tuple

from yoke_core.domain import (
    db_backend,
    migration_restore_point,
    migration_serving_version,
)
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module
from yoke_core.domain.migration_audit_receipts import now_stamp, write_receipt

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

LEDGER_TABLE = "applied_migrations"


@dataclass(frozen=True)
class ApplyOutcome:
    """What one ``apply_pending`` call did."""

    applied: Tuple[str, ...]
    restore_point: Optional[str]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def applied_names(conn: Any) -> Set[str]:
    """Return the migration names this database has recorded as applied."""
    rows = conn.execute(f"SELECT migration_name FROM {LEDGER_TABLE}").fetchall()
    return {str(row[0]) for row in rows}


def pending_entries(
    conn: Any, history: Sequence[MigrationEntry]
) -> Tuple[MigrationEntry, ...]:
    """Return the ordered entries this database has not applied.

    This is the one definition of "behind", shared by the apply path and the
    health gate, so a serving container and its health check can never
    disagree about whether it is current.

    Membership is by name, not by position: a database running *older*
    packaged code than its ledger — a rolled-back container — has an empty
    pending set and is correctly current, where a head-equality test would
    call it broken and refuse to serve in both directions.
    """
    recorded = applied_names(conn)
    return tuple(entry for entry in history if entry.name not in recorded)


def stamp_history(
    conn: Any, history: Sequence[MigrationEntry], *, applied_by: str
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
    stamped = [entry.name for entry in history]
    _record_applied(conn, stamped, applied_by=applied_by)
    conn.commit()
    return tuple(stamped)


def apply_pending(
    conn: Any,
    *,
    history: Sequence[MigrationEntry],
    applied_by: str,
    running_version: str = "",
    backup_root: Optional[Path] = None,
    external_restore_point: Optional[str] = None,
) -> ApplyOutcome:
    """Apply every entry this database still owes, oldest first.

    Exactly one restore-point source must be supplied. ``backup_root`` makes
    the kernel take a ``pg_dump`` itself, which is right where the database
    is local to the machine or its volume. ``external_restore_point`` names a
    restore point someone else established — the managed-Postgres snapshot a
    fleet roll takes before replacing any container, which is both faster than
    a per-database dump and, unlike one written inside a container about to be
    torn down, still there afterwards.

    Refusing when neither is present is the policy, not a precaution: nothing
    destructive runs without a named way back.

    ``running_version`` is the version of the artifact doing the applying. The
    kernel stays ignorant of what that means — the caller knows whether it is
    a wheel version, an image tag, or nothing at all — and an empty string is
    the honest answer from a source tree. It is compared against each entry's
    declared floor, so an entry can never be applied by a build too old to
    serve against the result, and it is recorded on the ledger row, because a
    build old enough to be in danger does not ship the entry that would tell
    it so.
    """
    if not history:
        return ApplyOutcome(applied=(), restore_point=None)

    # Cheap probe first. The overwhelming majority of boots are current, and
    # they should cost two queries and take no lock at all.
    if not pending_entries(conn, history):
        return ApplyOutcome(applied=(), restore_point=None)

    restore_point = migration_restore_point.establish(
        conn,
        backup_root=backup_root,
        external_restore_point=external_restore_point,
    )

    _acquire_apply_lock(conn)
    try:
        # Re-enumerate under the lock. Reading the pending set before taking
        # it is check-then-act: the boot guard other containers hold is a
        # *shared* lock, so two of them genuinely do converge at once, and
        # both would otherwise see the same work and race to do it.
        outstanding = pending_entries(conn, history)
        applied: list[str] = []
        for entry in outstanding:
            _apply_one(
                conn,
                entry,
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
    applied_by: str,
    running_version: str,
    restore_point: str,
) -> None:
    module = load_migration_module(entry.path, entry.name)
    minimum = migration_serving_version.declared_minimum(module)
    # Before the DDL, not after: an entry whose floor is newer than the build
    # running it means the declaration and the code disagree, and catching
    # that here costs nothing while catching it later costs the database.
    migration_serving_version.refuse_if_behind(entry.name, running_version, minimum)
    started_at = now_stamp()
    try:
        # apply() and the ledger row land together or not at all. The module
        # contract forbids committing inside apply() for exactly this reason.
        module.apply(conn)
        _record_applied(
            conn, [entry.name], applied_by=applied_by, minimum_serving_version=minimum
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — receipt, then fail the boot
        conn.rollback()
        write_receipt(
            conn,
            entry,
            state="live_apply_failed",
            started_at=started_at,
            completed_at=now_stamp(),
            restore_point=restore_point,
            failure_reason=str(exc)[:500],
        )
        raise

    invariants = getattr(module, "invariants", None)
    if callable(invariants):
        try:
            invariants(conn)
        except Exception as exc:  # noqa: BLE001 — receipt, then fail the boot
            write_receipt(
                conn,
                entry,
                state="live_verify_failed",
                started_at=started_at,
                completed_at=now_stamp(),
                restore_point=restore_point,
                failure_reason=str(exc)[:500],
            )
            raise

    write_receipt(
        conn,
        entry,
        state="completed",
        started_at=started_at,
        completed_at=now_stamp(),
        restore_point=restore_point,
    )


def _record_applied(
    conn: Any,
    names: Sequence[str],
    *,
    applied_by: str,
    minimum_serving_version: Optional[str] = None,
) -> None:
    """Write ledger rows, carrying each entry's declared floor.

    The floor is recorded rather than looked up later because the reader who
    needs it is a build that predates the entry and does not ship its module.
    The ledger row is the only surface the two share.
    """
    if not names:
        return
    p = _p(conn)
    now = now_stamp()
    for name in names:
        conn.execute(
            f"INSERT INTO {LEDGER_TABLE} "
            "(migration_name, applied_at, applied_by, minimum_serving_version) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT (migration_name) DO NOTHING",
            (name, now, applied_by, minimum_serving_version),
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
    "LEDGER_TABLE",
    "MIGRATION_APPLY_LOCK_KEY",
    "applied_names",
    "apply_pending",
    "pending_entries",
    "stamp_history",
]
