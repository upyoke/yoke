"""Real boot and export fixtures for universe import integration tests."""

from contextlib import contextmanager
from pathlib import Path

import psycopg

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import booted_universe_database
from yoke_core.domain import universe_export


@contextmanager
def _canonical_universe():
    with booted_universe_database() as name:
        dsn = pg_testdb.dsn_for_test_database(name)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn



def _exported_archive(source_dsn: str, tmp_path: Path) -> Path:
    return Path(
        universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
    )

