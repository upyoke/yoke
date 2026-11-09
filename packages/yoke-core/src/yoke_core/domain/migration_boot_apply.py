"""Apply the pending migration history to a database, in order, at boot.

A container starting on new code brings its own database up to that code
before it serves, so deployed and migrated cannot disagree. The kernel is
ignorant of whose history it applies — the caller passes one. Postgres
transactional DDL commits an entry's apply() with its ledger row. Rationale:
``docs/archive/decisions/ordered-cumulative-migrations.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from yoke_contracts.schema_authority import (
    refuse_without_serving_build_authority,
)
from yoke_core.domain import (
    administered_postgres,
    db_backend,
    migration_restore_point,
    migration_serving_version,
)
from yoke_core.domain.migration_apply_attribution import (
    refuse_level_as_model_name,
    require_attribution,
)
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_boot_ledger import (
    MIGRATION_APPLY_LOCK_KEY,
    acquire_apply_lock,
    applied_names,
    pending_entries,
    record_applied,
    release_apply_lock,
)
from yoke_core.domain.migration_content_identity import (
    raw_content_sha256,
    require_matching_content_identity,
)
from yoke_core.domain.migration_history import MigrationEntry, load_migration_module
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_audit_receipts import now_stamp, write_receipt
from yoke_core.domain.migration_entry_failure_cause import (
    EntryFailed,
    failure_reason,
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
    administering_env: str | None = None,
    running_version: str = "",
) -> Tuple[str, ...]:
    """Record the whole history as applied without running any of it.

    For a database that was just born: its schema came from the current code,
    so every historical entry is already true of it by construction and
    running them would be at best a no-op and at worst a corruption. The
    equivalent of Flyway's baseline or Django's fake-initial.

    Birth must be observed by the caller: an empty pre-ledger database
    still owes real migrations and must never be stamped.
    """
    refuse_without_serving_build_authority(
        "recording a migration history as applied",
        administering_env=(
            administered_postgres.administering_target(connection=conn)
            if administering_env is None
            else administering_env
        ),
    )
    require_matching_content_identity(conn, history, ledger)
    stamped: list[str] = []
    try:
        for entry in history:
            if entry.is_baseline:
                from yoke_core.domain.migration_baseline_collapse import (
                    baseline_recorded_floor,
                )

                record_applied(
                    conn,
                    entry,
                    ledger=ledger,
                    applied_by=applied_by,
                    content_sha256=entry.content_sha256,
                    minimum_serving_version=baseline_recorded_floor(
                        entry, running_version
                    ),
                )
                stamped.append(entry.name)
                continue
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
                minimum_serving_version=migration_serving_version.recorded_floor(
                    module,
                    running_version="",
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
    administering_env: str | None = None,
    running_version: str,
    attribution: Mapping[str, Any],
    model_name: str,
    dump_backup: Callable[[str, str, Path], str] | None = None,
    backup_root: Optional[Path] = None,
    backup_target_dsn: Optional[str] = None,
    external_restore_point: Optional[str] = None,
) -> ApplyOutcome:
    """Apply every entry this database still owes, in history order.

    A pending transition requires a named external restore point or a backup
    root and target supplied by composition. The applier owns the transaction:
    apply and membership commit together, and a baseline collapse is atomic.

    ``administering_env`` names the target authority, resolved from ``conn``
    when omitted. ``dump_backup`` is required only for a local backup.
    ``running_version`` is explicit; an empty source-tree version records no
    invented floor. A next-release entry records the carrying version.
    """
    refuse_without_serving_build_authority(
        "applying a migration history",
        administering_env=(
            administered_postgres.administering_target(connection=conn)
            if administering_env is None
            else administering_env
        ),
    )
    if not history:
        return ApplyOutcome(applied=(), restore_point=None)

    # A permanent name whose recorded non-NULL digest differs is corruption,
    # not pending work. Refuse before the current fast-path or any restore.
    from yoke_core.domain.migration_baseline_collapse import (
        baseline_transition_required,
        collapse_baseline,
    )

    baseline = next((entry for entry in history if entry.is_baseline), None)
    transition = baseline is not None and baseline_transition_required(
        conn, baseline, ledger
    )
    if not transition:
        require_matching_content_identity(conn, history, ledger)

    # Cheap probe first. The overwhelming majority of boots are current, and
    # they should cost two queries and take no lock at all. Attribution and
    # model_name are apply-time obligations: a current database must not
    # refuse because the process cannot name a commit.
    if not pending_entries(conn, history, ledger):
        return ApplyOutcome(applied=(), restore_point=None)

    provenance = require_attribution(attribution)
    model = refuse_level_as_model_name(model_name)

    restore_point = migration_restore_point.establish(
        conn,
        dump_backup=dump_backup,
        backup_root=backup_root,
        backup_target_dsn=backup_target_dsn,
        external_restore_point=external_restore_point,
    )

    acquire_apply_lock(conn)
    try:
        # Re-enumerate under the lock. Reading the pending set before taking
        # it is check-then-act: the boot guard other containers hold is a
        # *shared* lock, so two of them genuinely do converge at once, and
        # both would otherwise see the same work and race to do it.
        applied: list[str] = []
        if baseline is not None and collapse_baseline(
            conn,
            baseline,
            ledger,
            running_version=running_version,
            applied_by=applied_by,
        ):
            conn.commit()
            applied.append(baseline.name)
        require_matching_content_identity(conn, history, ledger)
        outstanding = pending_entries(conn, history, ledger)
        for entry in outstanding:
            _apply_one(
                conn,
                entry,
                ledger=ledger,
                applied_by=applied_by,
                running_version=running_version,
                restore_point=restore_point,
                attribution=provenance,
                model_name=model,
            )
            applied.append(entry.name)
        return ApplyOutcome(applied=tuple(applied), restore_point=restore_point)
    finally:
        release_apply_lock(conn)


def _apply_one(
    conn: Any,
    entry: MigrationEntry,
    *,
    ledger: LedgerContract,
    applied_by: str,
    running_version: str,
    restore_point: str,
    attribution: Mapping[str, str],
    model_name: str,
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
    declared = migration_serving_version.declared_minimum(module)
    # Refuse before DDL: a newer floor means the declaration and code disagree.
    # Catching it here costs nothing; catching it later costs the database.
    migration_serving_version.refuse_if_behind(entry.name, running_version, declared)
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
            minimum_serving_version=migration_serving_version.recorded_floor(
                module,
                running_version=running_version,
            ),
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
        reason = failure_reason(exc)
        write_receipt(
            conn,
            entry,
            state=failure_state,
            started_at=started_at,
            completed_at=now_stamp(),
            restore_point=restore_point,
            failure_reason=reason[:500],
            attribution=attribution,
            model_name=model_name,
        )
        raise EntryFailed(f"{entry.name} {failure_phase} failed -- {reason}") from exc

    write_receipt(
        conn,
        entry,
        state="completed",
        started_at=started_at,
        completed_at=now_stamp(),
        restore_point=restore_point,
        attribution=attribution,
        model_name=model_name,
    )


__all__ = [
    "ApplyOutcome",
    "EntryFailed",
    "MIGRATION_APPLY_LOCK_KEY",
    "applied_names",
    "apply_pending",
    "pending_entries",
    "stamp_history",
]
