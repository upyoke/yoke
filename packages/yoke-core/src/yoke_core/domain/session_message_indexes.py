"""Postgres-only indexes over session messages.

Wake-notice reads look messages up by idempotency-key prefix. Under a
non-C collation a plain btree cannot serve ``LIKE 'prefix%'``, so the index
uses the ``text_pattern_ops`` operator class, which only Postgres has.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend

IDEMPOTENCY_PREFIX_INDEX_NAME = "idx_session_messages_idempotency_prefix"


def create_session_message_prefix_index(conn: Any) -> None:
    """Index idempotency keys for prefix reads; other backends have no such class."""
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {IDEMPOTENCY_PREFIX_INDEX_NAME} "
        "ON session_messages(idempotency_key text_pattern_ops) "
        "WHERE idempotency_key IS NOT NULL"
    )


__all__ = ["IDEMPOTENCY_PREFIX_INDEX_NAME", "create_session_message_prefix_index"]
