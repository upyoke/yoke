"""Authored delivery-custody declaration on a deployment flow.

Whether a flow enrolls carried items is a statement on the flow row, not a
consequence of the stage vocabulary. ``definition_schema_version`` still
names which stage keys the executor is reading. Create may omit the flag:
the stored value then matches the behavior that schema version used to
imply, so existing callers keep their present custody without re-deriving
it on later stage edits.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_flow_policy import RELEASE_POLICY_SCHEMA_VERSION

COLUMN = "takes_delivery_custody"


def default_takes_delivery_custody(schema_version: int) -> bool:
    return int(schema_version) >= RELEASE_POLICY_SCHEMA_VERSION


def parse_takes_delivery_custody(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    raise ValueError("takes_delivery_custody must be a boolean")


def resolve_takes_delivery_custody(
    value: Any, *, schema_version: int
) -> bool:
    if value is None:
        return default_takes_delivery_custody(schema_version)
    return parse_takes_delivery_custody(value)


def as_sql_int(value: bool) -> int:
    return 1 if value else 0


def from_cell(value: Any) -> bool:
    if value is None:
        return False
    return parse_takes_delivery_custody(value)


__all__ = [
    "COLUMN",
    "as_sql_int",
    "default_takes_delivery_custody",
    "from_cell",
    "parse_takes_delivery_custody",
    "resolve_takes_delivery_custody",
]
