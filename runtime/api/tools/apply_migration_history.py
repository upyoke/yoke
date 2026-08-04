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

    python3 -m runtime.api.tools.apply_migration_history --dry-run
    python3 -m runtime.api.tools.apply_migration_history
"""

from __future__ import annotations

import argparse
import sys

from yoke_core.domain import db_helpers, migration_boot_apply
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.environment_bootstrap import universe_is_born_on
from yoke_core.domain.migration_audit_schema import ensure_applied_migrations_table
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.migration_restore_point import configured_restore_point


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
    args = parser.parse_args(argv)

    history = ordered_entries(history_dir(migration_history_package))
    print(f"history: {len(history)} entries")
    for entry in history:
        print(f"  {entry.name}")

    conn = db_helpers.connect()
    try:
        ensure_applied_migrations_table(conn)
        pending = migration_boot_apply.pending_entries(conn, history)
        applied = sorted(migration_boot_apply.applied_names(conn))
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
                conn, history, applied_by="operator-birth-stamp"
            )
            print(f"newborn database: stamped {len(stamped)} entries, applied none")
            return 0

        backup_root, external = configured_restore_point()
        outcome = migration_boot_apply.apply_pending(
            conn,
            history=history,
            applied_by="operator-apply-migration-history",
            backup_root=backup_root,
            external_restore_point=external,
        )
        print(f"restore point: {outcome.restore_point}")
        print(f"applied: {list(outcome.applied)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
