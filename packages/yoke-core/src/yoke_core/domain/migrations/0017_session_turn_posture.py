"""Add durable native-turn posture to existing harness sessions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _add_column_if_not_exists, _get_columns
from yoke_core.domain.session_turn_posture import (
    TURN_POSTURE_AT_COLUMN_DDL,
    TURN_POSTURE_COLUMN_DDL,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    _add_column_if_not_exists(
        conn, "harness_sessions", "turn_posture", TURN_POSTURE_COLUMN_DDL
    )
    _add_column_if_not_exists(
        conn, "harness_sessions", "turn_posture_at", TURN_POSTURE_AT_COLUMN_DDL
    )


def invariants(conn: Any) -> None:
    columns = set(_get_columns(conn, "harness_sessions"))
    missing = {"turn_posture", "turn_posture_at"} - columns
    assert not missing, (
        f"harness session turn posture columns missing: {sorted(missing)}"
    )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
