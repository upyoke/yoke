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

Two properties are worth stating because they are the reason to prefer this
shape over the mechanism it replaces:

*Applied and recorded are one transaction.* Postgres has transactional DDL,
so an entry's ``apply()`` and its ledger row commit together. The
"applied but unrecorded" state that forces other migration tools to carry
repair tooling cannot occur here — there is no window in which it exists.

*A failed entry stops the chain.* Boot is fail-hard. A container that cannot
migrate does not serve, because serving behind your own schema is the
failure this exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, Set, Tuple

from yoke_core.domain import db_backend, migration_restore_point
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module

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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            _apply_one(conn, entry, applied_by=applied_by, restore_point=restore_point)
            applied.append(entry.name)
        return ApplyOutcome(applied=tuple(applied), restore_point=restore_point)
    finally:
        _release_apply_lock(conn)


def _apply_one(
    conn: Any,
    entry: MigrationEntry,
    *,
    applied_by: str,
    restore_point: str,
) -> None:
    module = load_migration_module(entry.path, entry.name)
    started_at = _now()
    try:
        # apply() and the ledger row land together or not at all. The module
        # contract forbids committing inside apply() for exactly this reason.
        module.apply(conn)
        _record_applied(conn, [entry.name], applied_by=applied_by)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — receipt, then fail the boot
        conn.rollback()
        _write_receipt(
            conn,
            entry,
            state="live_apply_failed",
            started_at=started_at,
            restore_point=restore_point,
            failure_reason=str(exc)[:500],
        )
        raise

    invariants = getattr(module, "invariants", None)
    if callable(invariants):
        try:
            invariants(conn)
        except Exception as exc:  # noqa: BLE001 — receipt, then fail the boot
            _write_receipt(
                conn,
                entry,
                state="live_verify_failed",
                started_at=started_at,
                restore_point=restore_point,
                failure_reason=str(exc)[:500],
            )
            raise

    _write_receipt(
        conn,
        entry,
        state="completed",
        started_at=started_at,
        restore_point=restore_point,
    )


def _record_applied(conn: Any, names: Sequence[str], *, applied_by: str) -> None:
    if not names:
        return
    p = _p(conn)
    now = _now()
    for name in names:
        conn.execute(
            f"INSERT INTO {LEDGER_TABLE} (migration_name, applied_at, applied_by) "
            f"VALUES ({p}, {p}, {p}) ON CONFLICT (migration_name) DO NOTHING",
            (name, now, applied_by),
        )


def record_missing_receipts(
    conn: Any, history: Sequence[MigrationEntry], *, restore_point: str
) -> Tuple[str, ...]:
    """Write ``completed`` receipts for applied entries that have none.

    A receipt failure never fails an apply -- that is deliberate, since a boot
    must not die over evidence -- so "in the ledger, absent from
    ``migration_audit``" is a state this design can genuinely reach. Healing it
    belongs with the applier rather than in whatever hand-written SQL an
    operator reaches for at the time.

    The ledger is the proof the entry ran; *restore_point* is the one fact only
    the operator still holds, so it is passed in rather than guessed.
    """
    applied = applied_names(conn)
    recorded = {
        str(row[0])
        for row in conn.execute("SELECT migration_name FROM migration_audit").fetchall()
    }
    healed = [e for e in history if e.name in applied and e.name not in recorded]
    for entry in healed:
        _write_receipt(
            conn,
            entry,
            state="completed",
            started_at=_now(),
            restore_point=restore_point,
        )
    return tuple(e.name for e in healed)


def _write_receipt(
    conn: Any,
    entry: MigrationEntry,
    *,
    state: str,
    started_at: str,
    restore_point: str,
    failure_reason: Optional[str] = None,
) -> None:
    """Record a ``migration_audit`` row; never fail the apply over it.

    The ledger is the cursor and is authoritative. This row is evidence — in
    particular it is where an operator reads *which restore point covers this
    apply* after something has gone wrong, which is the moment when
    reconstructing that answer is hardest.

    ``tables_declared`` / ``expected_deltas`` / ``pre_row_counts`` are NOT NULL
    and are written empty on purpose. They carry the declared-delta bookkeeping
    of the rehearse-then-verify runner, which this path does not have and does
    not claim to: an entry here is trusted to be correct because it ran in
    order under a lock, not because its row counts were predicted in advance.
    Empty is the honest value; omitting the columns is a constraint violation.
    """
    p = _p(conn)
    try:
        conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, backup_path, failure_reason, "
            " started_at, completed_at, description, "
            " tables_declared, expected_deltas, pre_row_counts) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                entry.name,
                state,
                restore_point,
                failure_reason,
                started_at,
                _now(),
                "boot-converge apply from the ordered migration history",
                json.dumps([]),
                json.dumps({}),
                json.dumps({}),
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — evidence is not worth failing a boot
        conn.rollback()
        # Loud, but not fatal. A receipt that silently fails to write leaves an
        # apply with no record of which restore point covers it, and the first
        # time anyone notices is while recovering from something else. Swallowing
        # the failure is the right call for a boot; hiding it is not.
        print(
            f"WARNING: migration_audit receipt for {entry.name} "
            f"({state}) was not recorded: {exc}",
            file=sys.stderr,
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
