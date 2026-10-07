"""Least-privilege identity the hosted service uses to call a universe.

The hosted service (Platform, at upyoke.com) delivers a few facts only it
observes — GitHub App lifecycle, machine-authorization expiry — into each
tenant universe. It does so as one system actor holding one org role that
carries one permission. No human role carries that permission (the org
``admin`` wildcard excludes it), and the role is not offered by any member
grant or invite surface, so recognition never depends on a token's name.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_state import actor_is_active


HOSTED_SERVICE_COMPONENT = "hosted_service"
ROLE_HOSTED_SERVICE = "hosted_service"
PERM_HOSTED_SERVICE_DELIVER = "hosted_service.deliver"
HOSTED_SERVICE_TOKEN_NAME = "hosted-service"
HOSTED_SERVICE_MINT_COMMAND = (
    "python3 -m yoke_core.domain.api_tokens_cli hosted-service"
)

# Everything the hosted service identity may call. It inherits no signed-in
# baseline: no token minting, sessions, decision requests, or models.
HOSTED_SERVICE_FUNCTIONS = frozenset(
    {"projects.github_binding.lifecycle", "machine_approval.lifecycle.apply"}
)

ROLE_HOSTED_SERVICE_DESCRIPTION = (
    "The hosted service's own identity: deliver hosted lifecycle facts."
)
PERM_HOSTED_SERVICE_DELIVER_DESCRIPTION = (
    "Deliver hosted-service lifecycle facts (GitHub App binding lifecycle, "
    "machine-authorization expiry and withdrawal) into this org."
)


def hosted_service_org_ids(conn: Any, actor_id: int) -> frozenset[int]:
    """Return the orgs ``actor_id`` may deliver hosted-service facts into.

    Empty unless the actor is the active ``hosted_service`` system actor and
    an org role it holds carries ``hosted_service.deliver``.
    """
    if not actor_is_active(conn, actor_id):
        return frozenset()
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT aor.org_id FROM actors a "
        "JOIN actor_org_roles aor ON aor.actor_id = a.id "
        "JOIN role_permissions rp ON rp.role_id = aor.role_id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE a.id = {p} AND a.kind = 'system' "
        f"AND a.system_component = {p} AND perm.key = {p}",
        (actor_id, HOSTED_SERVICE_COMPONENT, PERM_HOSTED_SERVICE_DELIVER),
    ).fetchall()
    return frozenset(int(row[0]) for row in rows)


def is_hosted_service_actor(conn: Any, actor_id: int) -> bool:
    """True for the hosted service's system actor, whatever it currently holds."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {p} AND kind = 'system' "
        f"AND system_component = {p}",
        (actor_id, HOSTED_SERVICE_COMPONENT),
    ).fetchone()
    return row is not None


def hosted_service_scope_denial(function_id: str) -> str:
    """Name what the hosted service identity may call when it calls anything else."""
    allowed = ", ".join(sorted(HOSTED_SERVICE_FUNCTIONS))
    return (
        f"function {function_id!r} is outside the hosted service identity's "
        f"scope; system actor {HOSTED_SERVICE_COMPONENT!r} may call only "
        f"{allowed}. Call it with a member's or operator's own token instead"
    )


def hosted_service_denial_message(function_id: str) -> str:
    """Name the refused credential and the command that mints the right one."""
    return (
        f"function {function_id!r} requires the hosted service identity "
        f"(system actor {HOSTED_SERVICE_COMPONENT!r} holding "
        f"{PERM_HOSTED_SERVICE_DELIVER!r}); no member or admin token passes. "
        f"Mint that identity's token in this universe with "
        f"`{HOSTED_SERVICE_MINT_COMMAND}` and call with it"
    )


__all__ = [
    "HOSTED_SERVICE_COMPONENT",
    "HOSTED_SERVICE_FUNCTIONS",
    "HOSTED_SERVICE_MINT_COMMAND",
    "HOSTED_SERVICE_TOKEN_NAME",
    "PERM_HOSTED_SERVICE_DELIVER",
    "PERM_HOSTED_SERVICE_DELIVER_DESCRIPTION",
    "ROLE_HOSTED_SERVICE",
    "ROLE_HOSTED_SERVICE_DESCRIPTION",
    "hosted_service_denial_message",
    "hosted_service_org_ids",
    "hosted_service_scope_denial",
    "is_hosted_service_actor",
]
