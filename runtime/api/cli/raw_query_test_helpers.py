"""Shared Postgres helpers for raw-query tests."""

from __future__ import annotations

from yoke_core.domain import db_backend


def pg_conn():
    import psycopg

    from yoke_contracts.control_plane_locality import local_authority_exempt

    # Tests run against a local Postgres they own, so opening the authority
    # directly is the intent here rather than a call path that has to work
    # from a client machine.
    with local_authority_exempt():
        return psycopg.connect(db_backend.resolve_pg_dsn())


def connect(db_path: str):
    del db_path
    return pg_conn()
