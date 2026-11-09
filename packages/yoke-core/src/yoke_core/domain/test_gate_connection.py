"""Resolve the shared maintenance connection used by gate observers."""
from __future__ import annotations
import os
from typing import Optional

def maintenance_dsn() -> Optional[str]:
    """DSN for the shared cluster's maintenance database, or None.

    Shared with the worker budget, which arbitrates on the same cluster.
    """
    try:
        from yoke_core.domain import db_backend

        if os.environ.get(db_backend.PG_DSN_ENV) or os.environ.get(
            db_backend.PG_DSN_FILE_ENV
        ):
            base = db_backend.resolve_pg_dsn()
        else:
            from yoke_core.domain import test_postgres_cluster as pg_testcluster

            if not pg_testcluster._is_ready():
                return None
            base = pg_testcluster.dsn()
    except Exception:
        return None
    # libpq key/value DSN: a later dbname= key wins, so appending overrides.
    return f"{base} dbname=postgres"

