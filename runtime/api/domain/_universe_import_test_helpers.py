"""Real boot and export fixtures for universe import integration tests."""

from contextlib import contextmanager
from pathlib import Path

import psycopg

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import universe_export
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn


@contextmanager
def _canonical_universe():
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)



def _exported_archive(source_dsn: str, tmp_path: Path) -> Path:
    return Path(
        universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
    )

