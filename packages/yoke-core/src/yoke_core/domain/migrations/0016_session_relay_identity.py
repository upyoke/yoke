"""Converge actor and host identity on existing relay registrations.

The change is additive, but the unreleased entry carries the next-release
sentinel so its ledger floor resolves to the first artifact that ships it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.migration_session_relay_identity import (
    assert_relay_identity,
    converge_relay_identity,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    converge_relay_identity(conn)


def invariants(conn: Any) -> None:
    assert_relay_identity(conn)


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
