"""Shared Postgres helpers for raw-query tests."""

from __future__ import annotations

from yoke_core.domain import db_backend


def pg_conn():
    import psycopg

    return psycopg.connect(db_backend.resolve_pg_dsn())


def connect(db_path: str):
    del db_path
    return pg_conn()
