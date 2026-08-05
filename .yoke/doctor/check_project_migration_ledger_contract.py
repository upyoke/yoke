"""Whether a project's declared migration ledger satisfies rollback safety.

A declaration is a promise, and this reads the live rows to see whether the
promise holds. Membership alone is not enough: the serving floor must also
be readable so a rolled-back build can answer the serving question from the
ledger. The distinct outcomes matter more than the pass/fail split: a
ledger that cannot be read and a ledger that is level are opposite answers,
and reporting the first as the second is what this check exists to prevent.
"""

from __future__ import annotations

from typing import Any

SLUG = "project-migration-ledger-contract"
TITLE = "Declared migration ledger answers rollback-safety contract"


def hc_project_migration_ledger_contract(conn, args: Any, rec: Any) -> None:
    """Report whether the declared ledger satisfies the rollback-safety contract.

    N/A when the project declares no ledger: models predating the contract
    are legitimately silent, and calling that a failure would turn an
    absent opinion into a fleet-wide red.
    """
    from yoke_core.domain import migration_ledger_contract

    declaration = _declared_ledger(conn, rec)
    if declaration is None:
        rec.record(
            SLUG, TITLE, "N/A",
            "this project's migration_model declares no ledger",
        )
        return

    try:
        contract = migration_ledger_contract.parse(declaration)
    except migration_ledger_contract.LedgerContractError as exc:
        rec.record(SLUG, TITLE, "FAIL", str(exc))
        return

    try:
        rows = conn.execute(
            f"SELECT {contract.entry_column}, {contract.serving_floor_column} "
            f"FROM {contract.table}"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a finding
        # Never PASS here. "I could not read it" and "it is level" are
        # opposite answers and only one is safe to assume. Covers both the
        # entry identity column and the serving floor column.
        rec.record(
            SLUG, TITLE, "WARN",
            f"cannot read {contract.table}."
            f"{contract.entry_column}/{contract.serving_floor_column}: {exc}",
        )
        return

    applied = [str(row[0]) for row in rows]
    history = _shipped_history(rec)
    if history is None:
        return

    reason = migration_ledger_contract.unanswerable_reason(history, applied)
    if reason:
        rec.record(SLUG, TITLE, "FAIL", reason)
        return

    pending = migration_ledger_contract.pending_entries(history, applied)
    if pending:
        rec.record(
            SLUG, TITLE, "FAIL",
            f"{len(pending)} entry(ies) not applied here: {', '.join(pending)}",
        )
        return
    rec.record(
        SLUG, TITLE, "PASS",
        f"{len(applied)} applied entry(ies) answer membership; "
        f"serving floor readable via {contract.serving_floor_column}",
    )


def _declared_ledger(conn, rec: Any):
    """The project's ledger declaration, or ``None`` when it has none."""
    from yoke_core.domain import json_helper

    row = conn.execute(
        "SELECT settings FROM project_capabilities WHERE type = %s",
        ("migration_model",),
    ).fetchone()
    if not row or not row[0]:
        return None
    payload = json_helper.loads(row[0])
    models = (payload or {}).get("models") or {}
    default = (payload or {}).get("default_model") or ""
    model = models.get(default) or (next(iter(models.values()), None) or {})
    return ((model.get("runner") or {}).get("config") or {}).get("ledger")


def _shipped_history(rec: Any):
    """The migration entry names this build ships, or ``None`` on failure."""
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    try:
        return [e.name for e in ordered_entries(history_dir(
            migration_history_package))]
    except Exception as exc:  # noqa: BLE001 — a malformed history is a finding
        rec.record(
            SLUG, TITLE, "WARN",
            f"cannot read the packaged migration history: {exc}",
        )
        return None


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (SLUG, TITLE, hc_project_migration_ledger_contract),
)
