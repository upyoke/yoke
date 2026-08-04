"""Health check: has this database applied the migrations its code requires?

Replaces the stranded-migration-module check, which asked the opposite and
now-meaningless question — "is a completed migration's source still in the
tree?" — a question that only existed because migration sources used to be
deleted after they were applied. Under an ordered permanent history the
source is *always* present, and the thing worth checking is whether each
database has caught up to it.

Unlike its predecessor this needs no source checkout: the history ships in
the installed wheel and the ledger is a table, so the check answers on a
hosted runner exactly as it does on a developer machine.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "pending-migrations"
TITLE = "Pending migrations applied"


def hc_pending_migrations(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-pending-migrations: the ledger is level with the shipped history.

    FAIL when this database is behind: an entry the running code requires has
    not been applied here. That is the divergence the ordered history exists
    to surface, and reporting it as anything softer than a failure is what
    let a universe sit behind for a day without anyone noticing.

    A resolution failure is WARN with a named reason, never a silent PASS.
    The predecessor's pass-closed posture inverts dangerously under these
    semantics: "I could not read the ledger" and "the ledger is level" are
    opposite answers, and only one of them is safe to assume.
    """
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_boot_apply import pending_entries
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    try:
        history = ordered_entries(history_dir(migration_history_package))
    except Exception as exc:  # noqa: BLE001 — a malformed history is a finding
        rec.record(
            SLUG, TITLE, "WARN",
            f"cannot read the packaged migration history: {exc}",
        )
        return

    if not history:
        rec.record(SLUG, TITLE, "PASS", "")
        return

    try:
        pending = pending_entries(conn, history)
    except Exception as exc:  # noqa: BLE001 — cannot tell is not a pass
        rec.record(
            SLUG, TITLE, "WARN",
            "cannot read the applied_migrations ledger, so whether this "
            f"database is current is unknown: {exc}",
        )
        return

    if not pending:
        rec.record(SLUG, TITLE, "PASS", "")
        return

    issues: List[str] = [
        f"- {entry.name} (declared in the shipped history, absent from this "
        "database's ledger)"
        for entry in pending
    ]
    issues.append(
        "This database is behind the code running against it. A boot converge "
        "applies the pending set; if one has run and these remain, the apply "
        "failed and its migration_audit row names the restore point."
    )
    rec.record(SLUG, TITLE, "FAIL", "\n".join(issues))


__all__ = ["SLUG", "TITLE", "hc_pending_migrations"]
