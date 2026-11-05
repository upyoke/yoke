# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import io

import subprocess

from contextlib import contextmanager

import psycopg

import pytest

from yoke_core.domain import universe_portability as portability


@contextmanager
def _canonical_test_universe():
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)
