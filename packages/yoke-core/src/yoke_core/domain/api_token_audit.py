"""Non-secret audit records for API-token issuance and authentication."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.db_helpers import instant_parameter


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _metadata_json(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    ordered = {key: metadata[key] for key in sorted(metadata)}
    return json_helper.dumps_compact(ordered)


def record_token_audit(
    conn: Any,
    *,
    api_token_id: int | None,
    actor_id: int | None,
    event_type: str,
    outcome: str,
    project_id: int | None = None,
    permission_key: str | None = None,
    diagnostic_metadata: dict[str, Any] | None = None,
) -> None:
    """Append a non-secret auth audit row."""
    p = _p(conn)
    conn.execute(
        "INSERT INTO api_token_audit "
        "(api_token_id, actor_id, project_id, event_type, outcome, "
        "permission_key, diagnostic_metadata, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            api_token_id,
            actor_id,
            project_id,
            event_type,
            outcome,
            permission_key,
            _metadata_json(diagnostic_metadata),
            instant_parameter(conn, utc_now()),
        ),
    )
    conn.commit()
