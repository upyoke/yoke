"""Resolve a deployment flow's declared deploy target to a storable row.

One place decides what ``target_tier`` plus ``environment`` mean, so every
writer of ``deployment_flows`` agrees: a persistent flow names exactly one
registered environment, an ephemeral flow deploys per-run substrate and
names none, and a merge-only flow declares neither.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.deployment_flow_target_tier import (
    TARGET_TIER_PERSISTENT,
    VALID_TARGET_TIERS,
)
from yoke_core.domain.project_identity import resolve_project


def resolve_flow_target(
    conn: Any,
    *,
    project: str,
    target_tier: Optional[str],
    environment: Optional[str],
) -> Optional[int]:
    """Return the ``target_environment_id`` the declared target implies."""
    if target_tier is not None and target_tier not in VALID_TARGET_TIERS:
        raise ValueError(
            f"target_tier must be one of {sorted(VALID_TARGET_TIERS)} or null"
        )
    if (target_tier == TARGET_TIER_PERSISTENT) != bool(environment):
        raise ValueError(
            "environment is required exactly when "
            f"target_tier='{TARGET_TIER_PERSISTENT}'"
        )
    if not environment:
        return None
    ident = resolve_project(conn, project)
    assert ident is not None
    from yoke_core.domain.environment_reference import resolve

    return resolve(conn, project_id=ident.id, name=environment).id


__all__ = ["resolve_flow_target"]
