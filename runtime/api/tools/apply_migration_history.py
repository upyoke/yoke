"""Apply the pending migration history to the connected authoritative database.

Boot converge is how a database normally reaches its code, and it needs no
operator. This is the narrow manual trigger for the case where converge cannot
run end to end -- an unrelated convergence step failing ahead of the history,
say -- and an operator needs the history applied on its own.

It runs the SAME applier the boot path runs. It does not reimplement ordering,
locking, ledger writes, or receipts, and it deliberately does NOT run the rest
of the converge: this tool answers "apply what this database owes", nothing
else.

A restore point is taken before anything is applied, because the applier
refuses without one. On a machine-local or tunnelled Postgres that is a
``pg_dump`` under the Yoke state directory; a deployment that has already
established one exports ``YOKE_MIGRATION_RESTORE_POINT`` and this reuses it.

After apply, every table whose owner drifted during this apply is handed
back to the serving role. Gate the admin-apply recipe on the ownership
report that follows — this tool exits non-zero when apply-caused drift
remains, and ``repair_table_ownership`` still reports any leftover tables:

    python3 -m runtime.api.tools.apply_migration_history
    python3 -m runtime.api.tools.repair_table_ownership <env>

    python3 -m runtime.api.tools.apply_migration_history --dry-run
    python3 -m runtime.api.tools.apply_migration_history
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yoke_core.domain import (
    db_backend,
    db_helpers,
    migration_audit_receipts,
    migration_boot_apply,
    migration_fleet_ownership,
)
from yoke_core.domain.migration_apply_attribution import (
    IncompleteAttributionError,
    LaneAsModelNameError,
    collect_operator_attribution,
)
from yoke_core.domain.migration_model_capability_defaults import DEFAULT_MODEL_NAME
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.environment_bootstrap import universe_is_born_on
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.migration_restore_point import configured_restore_point
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    ensure_yoke_migration_ledger,
)
from yoke_contracts.engine_version import installed_engine_version


#: Tables this tool can bring into existence. Only these are handed back —
#: anything else that disagrees with the majority owner was not created here
#: and is not this tool's to reassign.
_TABLES_THIS_TOOL_CREATES = ("applied_migrations", "migration_audit")


def _realign_apply_caused_drift(conn, before_drifted: set[str]) -> int:
    """Hand back tables that drifted during this apply. Return 1 if any remain."""
    report = migration_fleet_ownership.inspect(conn)
    caused = [table for table, _owner in report.drifted if table not in before_drifted]
    if caused:
        altered = migration_fleet_ownership.realign(
            conn, tables=caused, owner=report.expected_owner
        )
        conn.commit()
        for table in altered:
            print(f"handed {table} back to {report.expected_owner}")
        report = migration_fleet_ownership.inspect(conn)
    print(f"ownership: {report.summary}")
    remaining = {table for table, _owner in report.drifted}
    return 1 if any(table in remaining for table in caused) else 0


def _hand_created_tables_to_the_serving_role(conn) -> None:
    """Give back any table this admin connection just created.

    ``ensure_yoke_migration_ledger`` creates the ledger when it is absent,
    and whoever runs it owns whatever it creates. Run through an admin
    connection — the only way this tool is run — that leaves the server unable
    to ever add a column to its own ledger, and the boot converge does exactly
    that. The failure surfaces much later as a tenant crash-looping at boot,
    with an error that reads like a missing column because Postgres resolves
    identifiers before it checks privileges. One instance took a production
    control plane down for twenty-five minutes.

    So the tool hands back what it made, at once, rather than leaving a trap
    for a release months away.
    """
    report = migration_fleet_ownership.inspect(conn)
    created = [t for t, _o in report.drifted if t in _TABLES_THIS_TOOL_CREATES]
    if not created:
        return
    altered = migration_fleet_ownership.realign(
        conn, tables=created, owner=report.expected_owner
    )
    conn.commit()
    for table in altered:
        print(f"handed {table} back to {report.expected_owner}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="apply-migration-history",
        description=(
            "Apply pending ordered-history migrations to the connected "
            "authoritative database."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the pending set and exit without applying or backing up.",
    )
    parser.add_argument(
        "--record-missing-receipts",
        metavar="RESTORE_POINT",
        help=(
            "Write completed receipts for entries already in the ledger that "
            "have no migration_audit row, naming RESTORE_POINT as the backup "
            "covering them. Applies nothing."
        ),
    )
    parser.add_argument(
        "--project-id",
        type=int,
        help="Attribute healed receipts to this project (evidence readers filter on it).",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="Attribute receipts to this migration model (not an execution lane).",
    )
    args = parser.parse_args(argv)

    history = ordered_entries(history_dir(migration_history_package))
    print(f"history: {len(history)} entries")
    for entry in history:
        print(f"  {entry.name}")

    conn = db_helpers.connect()
    try:
        ensure_yoke_migration_ledger(conn, repair_existing_guards=True)
        _hand_created_tables_to_the_serving_role(conn)
        try:
            attribution = collect_operator_attribution(conn, worktree=Path.cwd())
        except IncompleteAttributionError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if args.record_missing_receipts:
            healed = migration_audit_receipts.record_missing_receipts(
                conn,
                history,
                applied=migration_boot_apply.applied_names(
                    conn, YOKE_LEDGER_CONTRACT,
                ),
                stamp=migration_audit_receipts.now_stamp(),
                restore_point=args.record_missing_receipts,
                project_id=args.project_id,
                model_name=args.model_name,
                attribution=attribution,
            )
            print(f"recorded receipts: {list(healed)}")
            return 0
        pending = migration_boot_apply.pending_entries(
            conn, history, YOKE_LEDGER_CONTRACT,
        )
        applied = sorted(
            migration_boot_apply.applied_names(conn, YOKE_LEDGER_CONTRACT)
        )
        print(f"ledger: {len(applied)} applied {applied}")
        print(f"pending: {[e.name for e in pending]}")

        if not pending:
            print("nothing to apply")
            return 0
        if args.dry_run:
            print("dry-run: not applying")
            return 0
        if not universe_is_born_on(conn):
            # A database with no org card got its schema from current code and
            # already satisfies every entry; running them would be a no-op at
            # best. Stamping is the correct answer, and it is what boot does.
            stamped = migration_boot_apply.stamp_history(
                conn,
                history,
                ledger=YOKE_LEDGER_CONTRACT,
                applied_by="operator-birth-stamp",
            )
            print(f"newborn database: stamped {len(stamped)} entries, applied none")
            return 0

        backup_root, external = configured_restore_point()
        before = migration_fleet_ownership.inspect(conn)
        try:
            outcome = migration_boot_apply.apply_pending(
                conn,
                history=history,
                ledger=YOKE_LEDGER_CONTRACT,
                applied_by="operator-apply-migration-history",
                running_version=installed_engine_version(),
                attribution=attribution,
                model_name=args.model_name,
                backup_root=backup_root,
                backup_target_dsn=(
                    db_backend.resolve_pg_dsn() if backup_root is not None else None
                ),
                external_restore_point=external,
            )
        except LaneAsModelNameError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"restore point: {outcome.restore_point}")
        print(f"applied: {list(outcome.applied)}")
        return _realign_apply_caused_drift(
            conn, {table for table, _owner in before.drifted}
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
