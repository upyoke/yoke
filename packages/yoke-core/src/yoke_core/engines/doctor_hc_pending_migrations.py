"""Health check for the selected project's declared history and ledger."""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "pending-migrations"
TITLE = "Pending migrations applied"


def hc_pending_migrations(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-pending-migrations: selected project history minus its own ledger."""
    from yoke_core.domain import migration_ledger_contract
    from yoke_core.engines.doctor_project_migration_state import (
        MigrationAuthorityUnavailable,
        MigrationConfigurationError,
        NoMigrationModel,
        ledger_rows,
        resolve_project_migration_state,
    )

    try:
        state = resolve_project_migration_state(conn, args)
    except NoMigrationModel as exc:
        rec.record(SLUG, TITLE, "N/A", str(exc))
        return
    except MigrationConfigurationError as exc:
        rec.record(SLUG, TITLE, "FAIL", str(exc))
        return
    except MigrationAuthorityUnavailable as exc:
        rec.record(SLUG, TITLE, "WARN", str(exc))
        return

    try:
        try:
            applied = [name for name, _floor, _digest in ledger_rows(state)]
        except Exception as exc:  # noqa: BLE001 - cannot tell is not green
            rec.record(
                SLUG,
                TITLE,
                "WARN",
                f"cannot read {state.project}.{state.model_name} ledger "
                f"{state.ledger.table}: {exc}",
            )
            return
        history = [entry.name for entry in state.history]
        pending = migration_ledger_contract.pending_entries(history, applied)
        newer = migration_ledger_contract.applied_entries_outside_history(
            history, applied,
        )
        if not pending:
            rollback = (
                f", {len(newer)} newer applied row(s) outside this packaged "
                "history"
                if newer else ""
            )
            rec.record(
                SLUG,
                TITLE,
                "PASS",
                f"{state.project}.{state.model_name}: {len(applied)} applied, "
                f"0 pending{rollback}",
            )
            return
        issues: List[str] = [
            f"- {name} (declared in {state.project}.{state.model_name} "
            "history, absent from that model's ledger)"
            for name in pending
        ]
        issues.append(
            "The declared database is behind the selected project's code. "
            "Run that project's boot converge and inspect its migration audit."
        )
        rec.record(SLUG, TITLE, "FAIL", "\n".join(issues))
    finally:
        state.close()


__all__ = ["SLUG", "TITLE", "hc_pending_migrations"]
