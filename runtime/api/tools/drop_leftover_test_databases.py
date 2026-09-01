"""Drop leftover acceptance-test databases from the selected cluster.

Operator-debug tool. Acceptance and preflight runs occasionally leave
``yoke_test_run*`` databases behind on a cluster; each leftover pays
converge time on every subsequent fleet preflight. This tool removes
them safely:

- only names starting with the fixed ``yoke_test_run`` prefix are
  eligible — anything else is refused, whatever the operator passes;
- a database with live connections is skipped and reported;
- ``DROP DATABASE`` needs autocommit, which the transactional
  ``db_router query`` escape hatch cannot provide — that is why this
  is a dedicated tool.

Usage (against the connection selected by ``YOKE_ENV``):

    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.drop_leftover_test_databases [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from yoke_core.domain import db_backend

ELIGIBLE_PREFIX = "yoke_test_run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be dropped without dropping",
    )
    args = parser.parse_args(argv)

    conn = db_backend.connect()
    conn.autocommit = True
    rows = conn.execute(
        "SELECT datname, numbackends FROM pg_stat_database"
        " WHERE datname LIKE %s ORDER BY datname",
        (ELIGIBLE_PREFIX + "%",),
    ).fetchall()
    if not rows:
        print(f"no {ELIGIBLE_PREFIX}* databases on this cluster")
        return 0

    failures = 0
    for datname, numbackends in rows:
        if not str(datname).startswith(ELIGIBLE_PREFIX):
            print(f"refused {datname}: outside eligible prefix")
            failures += 1
            continue
        if numbackends:
            print(f"skipped {datname}: {numbackends} live connection(s)")
            failures += 1
            continue
        if args.dry_run:
            print(f"would drop {datname}")
            continue
        conn.execute(f'DROP DATABASE IF EXISTS "{datname}"')
        print(f"dropped {datname}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
