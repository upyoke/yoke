"""Add durable native-turn posture to existing harness sessions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_is_not_null,
    _get_check_constraint_defs,
    _get_column_default,
    _get_columns,
)
from yoke_core.domain.session_turn_posture import (
    TURN_POSTURE_AT_COLUMN_DDL,
    TURN_POSTURE_COLUMN_DDL,
)


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
    assert _column_is_not_null(conn, "harness_sessions", "turn_posture"), (
        "harness session turn posture must be NOT NULL"
    )
    raw_default = _get_column_default(conn, "harness_sessions", "turn_posture")
    default = str(raw_default or "").strip().split("::", maxsplit=1)[0]
    assert default.strip("() '\"") == "unknown", (
        "harness session turn posture must default to unknown"
    )
    checks = _get_check_constraint_defs(conn, "harness_sessions")
    posture_check = next(
        (
            definition
            for definition in checks
            if "turn_posture" in definition
            and all(
                posture in definition for posture in ("running", "waiting", "unknown")
            )
        ),
        None,
    )
    assert posture_check is not None, (
        "harness session turn posture must constrain the supported domain"
    )


__all__ = ["apply", "invariants"]
