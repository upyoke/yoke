"""Resolve the coordination claim row a release request names."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.coordination_claim_keys import target_for_key


def release_target_id(
    conn: Any, *, claim_id: Optional[int], project_id: Optional[str], key: Optional[str]
) -> int:
    """Resolve the claim row this release names, by id or by key."""
    if claim_id is not None:
        return int(claim_id)
    if not key or not project_id:
        raise ValueError("release requires claim_id, or project_id together with key")
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.project_identity import resolve_project

    identity = resolve_project(conn, project_id)
    assert identity is not None
    claim = active_claim(conn, target_for_key(key, project_id=identity.id))
    if claim is None:
        raise LookupError(f"no active coordination claim for {identity.slug}:{key}")
    return int(claim.id)
