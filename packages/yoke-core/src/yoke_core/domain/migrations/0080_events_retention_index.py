"""Verify the nonblocking, additive event retention index."""

from yoke_core.domain.events_retention_index import (
    ensure_retention_index,
    verify_retention_index,
)


def apply(conn) -> None:
    ensure_retention_index(conn)


def invariants(conn) -> None:
    verify_retention_index(conn)
