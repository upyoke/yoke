"""Drop the per-machine launch defaults relays used to advertise.

Each relay heartbeat once carried its machine's configured launch model and
effort maps, and a launch resolved its defaults from them. Level options
replaced both: a launch names a level, or an exact selection for one launch,
and no reader consults a machine's advertised defaults any more.

The serving floor keeps an older build, which writes both columns on every
heartbeat, from serving against a database that no longer has them. The
model-selection entry asserted one of these columns; its invariants retire
here, and the launch-selection columns it also asserted stay guaranteed by the
session-control schema convergence.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0038_session_launch_model_selection",)
TABLE = "session_relays"
RETIRED_COLUMNS = (
    "preferred_session_models",
    "preferred_session_reasoning_efforts",
)


def apply(conn: Any) -> None:
    """Drop each retired column an older database still carries."""
    if not _table_exists(conn, TABLE):
        return
    for column in RETIRED_COLUMNS:
        if _column_exists(conn, TABLE, column):
            conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{column}"')


def invariants(conn: Any) -> None:
    """Prove the retired columns are absent wherever the table exists."""
    if not _table_exists(conn, TABLE):
        return
    for column in RETIRED_COLUMNS:
        assert not _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} must be absent after convergence"
        )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMNS",
    "RETIRES_INVARIANTS",
    "TABLE",
    "apply",
    "invariants",
]
