"""Update-status fixtures release database authority before the next test."""

import gc
import os

import pytest

from runtime.api import test_update_status_full_misc
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import db_backend


def test_misc_environment_teardown_cannot_repoint_a_later_test(tmp_path):
    fixture = test_update_status_full_misc.env.__wrapped__(tmp_path)
    environment = next(fixture)
    # A failed test's traceback can retain its environment until cyclic GC.
    retained = [environment]
    retained.append(retained)
    try:
        with pytest.raises(StopIteration):
            next(fixture)
        with test_database() as conn:
            expected = os.environ[db_backend.PG_DSN_ENV]
            environment = None
            del retained
            gc.collect()
            assert os.environ[db_backend.PG_DSN_ENV] == expected
            with db_backend.connect() as ambient:
                assert ambient.info.dbname == conn.info.dbname
    finally:
        # Close even when this regression runs against the leaking fixture.
        if environment is not None:
            environment.close()
