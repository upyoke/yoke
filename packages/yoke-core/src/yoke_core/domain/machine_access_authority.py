"""One read for "may this actor use this machine's capacity?".

The registry's access document is the only source. Every surface that spends a
machine's capacity asks here rather than reimplementing the rule, so a machine
cannot be reachable through one door and closed through another.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.machine_access import (
    AccessDecision,
    USE_SETTING,
    access_permits,
)
from yoke_core.domain.machine_registry import get_machine, marker


REGISTRY_SETTING = "machines.registration"


def _project_role_names(
    conn: Any, *, actor_id: int, project_id: int
) -> tuple[str, ...]:
    """Role names this actor holds on one project, org-granted or direct."""
    p = marker(conn)
    org_rows = conn.execute(
        "SELECT r.name FROM projects pr "
        "JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE pr.id = {p} AND aor.actor_id = {p}",
        (int(project_id), int(actor_id)),
    ).fetchall()
    project_rows = conn.execute(
        "SELECT r.name FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {p} AND apr.project_id = {p}",
        (int(actor_id), int(project_id)),
    ).fetchall()
    names = {str(row[0]) for row in org_rows} | {str(row[0]) for row in project_rows}
    return tuple(sorted(names))


def actor_administers_project(conn: Any, *, actor_id: int, project_id: int) -> bool:
    from yoke_core.domain.actor_permissions import (
        PERM_PROJECT_ADMIN,
        permission_decision,
    )

    return permission_decision(
        conn,
        actor_id=int(actor_id),
        project_id=int(project_id),
        permission_key=PERM_PROJECT_ADMIN,
    ).allowed


def actor_may_use_machine(
    conn: Any,
    *,
    machine_id: str,
    actor_id: int,
    project_id: int,
    is_admin: bool = False,
) -> AccessDecision:
    """Decide whether this actor may spend ``machine_id``'s capacity.

    Administrator standing is resolved by the caller and passed in, because
    every surface that consumes machine capacity has already established the
    calling actor's project authority to get this far — resolving it a second
    time here would ask the permission catalog the same question twice per
    request.

    An unregistered machine admits nobody: capacity whose owner and settings
    are unknown cannot be checked, and silently allowing it would reintroduce
    the asserted-identity hole the registry exists to close.
    """
    record = get_machine(conn, machine_id)
    if record is None:
        return AccessDecision(
            False,
            REGISTRY_SETTING,
            f"machine {machine_id} is not registered in this control plane. "
            "Recovery: run `yoke machine register` on that machine.",
        )
    roles: tuple[str, ...] = ()
    declared_project = record.access["use"].get("project_id") or project_id
    if record.access["use"].get("role"):
        roles = _project_role_names(
            conn, actor_id=int(actor_id), project_id=int(declared_project)
        )
    return access_permits(
        record.access,
        actor_id=int(actor_id),
        owner_actor_id=int(record.owner_actor_id),
        is_admin=bool(is_admin),
        project_role_names=roles,
    )


__all__ = [
    "REGISTRY_SETTING",
    "USE_SETTING",
    "actor_administers_project",
    "actor_may_use_machine",
]
