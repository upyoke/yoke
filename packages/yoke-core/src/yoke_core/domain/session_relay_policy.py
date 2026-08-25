"""Organization policy projection for machine-relay cadence and retries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.organization_contract.fleet_keys import (
    FleetSettingsError,
    get_fleet_setting,
    validate_fleet_settings,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_relay_types import RelayPolicy, SessionRelayError


_POLICY_PATHS = {
    "poll_seconds": "fleet.relay_poll_seconds",
    "idle_after_minutes": "fleet.relay_idle_after_minutes",
    "idle_poll_minutes": "fleet.relay_idle_poll_minutes",
    "max_wake_attempts": "fleet.max_wake_attempts",
    "launch_batch": "fleet.relay_launch_batch",
    "launch_stagger_seconds": "fleet.relay_launch_stagger_seconds",
}


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _policy_from_document(document: Mapping[str, Any]) -> RelayPolicy:
    values = {
        name: int(get_fleet_setting(document, path)[0])
        for name, path in _POLICY_PATHS.items()
    }
    return RelayPolicy(**values)


def default_relay_policy() -> RelayPolicy:
    return _policy_from_document({})


def effective_relay_policy(
    conn: Any,
    project_ids: Sequence[int],
) -> RelayPolicy:
    """Return the strictest cadence across represented project organizations."""
    normalized = sorted({int(project_id) for project_id in project_ids})
    if not normalized or not _table_exists(conn, "organizations"):
        return default_relay_policy()
    if not _column_exists(conn, "organizations", "settings") or not _column_exists(
        conn, "projects", "org_id"
    ):
        return default_relay_policy()
    marker = _marker(conn)
    placeholders = ",".join(marker for _ in normalized)
    rows = conn.execute(
        "SELECT DISTINCT o.settings FROM organizations o "
        "JOIN projects p ON p.org_id=o.id "
        f"WHERE p.id IN ({placeholders})",
        tuple(normalized),
    ).fetchall()
    policies: list[RelayPolicy] = []
    try:
        for row in rows:
            document = json_helper.loads_text(str(row[0] or "{}"))
            if not isinstance(document, dict):
                raise FleetSettingsError("organization settings root must be an object")
            validate_fleet_settings(document)
            policies.append(_policy_from_document(document))
    except (TypeError, ValueError, FleetSettingsError) as exc:
        raise SessionRelayError(
            "relay_policy_invalid",
            f"organization fleet settings cannot drive relay polling: {exc}",
        ) from exc
    if not policies:
        return default_relay_policy()
    return RelayPolicy(
        poll_seconds=min(policy.poll_seconds for policy in policies),
        idle_after_minutes=min(policy.idle_after_minutes for policy in policies),
        idle_poll_minutes=min(policy.idle_poll_minutes for policy in policies),
        max_wake_attempts=min(policy.max_wake_attempts for policy in policies),
        launch_batch=min(policy.launch_batch for policy in policies),
        launch_stagger_seconds=max(
            policy.launch_stagger_seconds for policy in policies
        ),
    )


__all__ = ["default_relay_policy", "effective_relay_policy"]
