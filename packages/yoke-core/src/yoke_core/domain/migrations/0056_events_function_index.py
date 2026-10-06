"""Verify the nonblocking, additive event function identity lookup."""

from yoke_core.domain.events_function_index import (
    ensure_function_index,
    verify_function_index,
)


def apply(conn) -> None:
    ensure_function_index(conn)


def invariants(conn) -> None:
    verify_function_index(conn)
