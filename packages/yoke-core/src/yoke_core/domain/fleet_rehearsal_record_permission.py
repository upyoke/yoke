"""The permission one environment-settings merge actually needs.

``projects.environment_settings.merge`` is project administration by default.
A merge whose every assignment lies under ``release.fleet_rehearsal.`` is a
fleet rehearsal receipt, so it needs only ``release.fleet_rehearsal.record``:
the ``preflight_executor`` role carries it, and owner and admin carry it
through their wildcards. Any other path in the same merge — or an empty or
malformed assignment set, which the handler refuses anyway — keeps the
project-admin requirement, so the narrow permission never reaches another key.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.fleet_rehearsal_record_authority import (
    FLEET_REHEARSAL_MERGE_FUNCTION,
    PERM_FLEET_REHEARSAL_RECORD,
    is_fleet_rehearsal_path,
)


def is_fleet_rehearsal_merge(function_id: str, payload: Any) -> bool:
    """True when the call merges only paths inside the receipt namespace."""
    if function_id != FLEET_REHEARSAL_MERGE_FUNCTION or not isinstance(payload, dict):
        return False
    assignments = payload.get("assignments")
    if not isinstance(assignments, dict) or not assignments:
        return False
    return all(is_fleet_rehearsal_path(path) for path in assignments)


def effective_permission_key(
    function_id: str, payload: Any, permission_key: str | None
) -> str | None:
    """The permission this call needs: narrowed for a receipt-only merge."""
    if is_fleet_rehearsal_merge(function_id, payload):
        return PERM_FLEET_REHEARSAL_RECORD
    return permission_key


__all__ = ["effective_permission_key", "is_fleet_rehearsal_merge"]
