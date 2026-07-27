"""Decision-request schema support for API fixtures."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)


def create_decision_schema(conn: Any) -> None:
    """Create identity, authority, event, and decision-request tables."""
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    ensure_event_schema(conn)
    create_decision_request_tables(conn)


__all__ = ["create_decision_schema"]
