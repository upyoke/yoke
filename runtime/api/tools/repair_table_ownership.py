"""Report and repair tables the serving role cannot converge.

A table created by a role other than the one the server connects as can never
afterwards gain a column, because Postgres only lets an owner alter its table.
The boot converge does exactly that, so such a table is a latent boot failure
that fires on the next release touching it — arbitrarily later, with nothing
connecting the two. One instance took a production control plane down.

Reports by default. A repair requires ``--apply`` AND an explicit ``--table``
per table: a differently-owned table is not automatically wrong, since a
separately provisioned surface may legitimately own its own, so a repair
states what it is fixing rather than sweeping.

Usage::

    python3 -m runtime.api.tools.repair_table_ownership <env> [--dbname DB]
    python3 -m runtime.api.tools.repair_table_ownership <env> --apply --table t

where *env* is a configured admin connection (``prod-db-admin``,
``stage-db-admin``). Exits non-zero when drift remains, so a release step can
gate on it.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env", help="configured admin connection")
    parser.add_argument("--dbname", default=None, help="database to inspect")
    parser.add_argument(
        "--expected-owner",
        default=None,
        help="override the majority-owner inference",
    )
    parser.add_argument(
        "--table",
        action="append",
        default=None,
        help="repair only this table; repeatable and required with --apply",
    )
    parser.add_argument("--apply", action="store_true", help="perform the repair")
    args = parser.parse_args(argv)

    os.environ["YOKE_ENV"] = args.env
    from yoke_core.domain import db_backend, migration_fleet_ownership

    dsn = (
        db_backend.resolve_pg_dsn(dbname=args.dbname)
        if args.dbname
        else db_backend.resolve_pg_dsn()
    )
    conn = db_backend.connect_psycopg(dsn)
    try:
        report = migration_fleet_ownership.inspect(
            conn, expected_owner=args.expected_owner
        )
        print(report.summary)
        if report.uniform:
            return 0
        if not args.apply:
            print("\nreporting only; pass --apply --table NAME to repair")
            return 1
        if not args.table:
            print("\nrefusing a blanket repair; name each --table to fix")
            return 1

        drifted = {table for table, _owner in report.drifted}
        unknown = sorted(set(args.table) - drifted)
        if unknown:
            print(f"not drifted, nothing to do: {unknown}")
        altered = migration_fleet_ownership.realign(
            conn, tables=[t for t in args.table if t in drifted],
            owner=report.expected_owner,
        )
        conn.commit()
        for table in altered:
            print(f"repaired: {table} -> {report.expected_owner}")

        remaining = migration_fleet_ownership.inspect(
            conn, expected_owner=args.expected_owner
        )
        print(remaining.summary)
        return 0 if remaining.uniform else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
