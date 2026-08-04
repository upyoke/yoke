"""Rehearse the pending migration history against every live tenant database.

Run this before releasing a build that carries an unapplied history entry. It
answers the only question that matters about such an entry — does it still
apply to the databases that are behind? — by running it against a copy of
each of them, on the local embedded cluster, exactly as a booting container
would. The live databases are only read.

Usage::

    python3 -m runtime.api.tools.preflight_fleet_migrations <env-name> [db ...]

where *env-name* is a configured admin connection (``prod-db-admin`` or
``stage-db-admin``). Naming databases limits the run to those; the default is
every tenant database on that cluster.

Exits non-zero when any database fails, so a release step can gate on it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2

    os.environ["YOKE_ENV"] = args[0]
    from yoke_core.domain import db_backend, local_universe, migration_fleet_preflight

    spec = local_universe.cluster_spec(
        bin_dir=local_universe.ensure_engine_binaries(lambda msg: print(f"  {msg}"))
    )

    def dsn_for(database: str) -> str:
        return db_backend.resolve_pg_dsn(dbname=database)

    databases = args[1:] or None
    print(f"environment: {args[0]}")
    print(f"rehearsal cluster: {spec.sock_dir}")

    with tempfile.TemporaryDirectory(prefix="yoke-migration-rehearsal-") as work:
        verdicts = migration_fleet_preflight.rehearse_fleet(
            dsn_for, spec=spec, work_dir=Path(work), databases=databases
        )

    for verdict in verdicts:
        print(verdict.line)
    failed = [v for v in verdicts if not v.passed]
    print(f"\n{len(verdicts) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
