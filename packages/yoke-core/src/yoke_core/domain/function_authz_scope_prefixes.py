"""Function-id prefix families where every member shares one authz scope.

Split from :mod:`yoke_core.domain.function_authz_scope` so that module
stays inside the authored-file line budget. A prefix entry classifies a
whole family at once; anything needing a different answer than its
family gets an explicit by-id entry there, which wins.
"""

from __future__ import annotations

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
)
from yoke_core.domain.function_authz_types import (
    ACTOR_SESSION,
    AuthzSpec,
    CLIENT_LOCAL,
    ORG,
    PROJECT,
)

AUTHZ_BY_PREFIX: tuple[tuple[str, AuthzSpec], ...] = (
    # Global learning channel; handlers retain optional project list filters.
    ("ouroboros.field_note.", AuthzSpec(ACTOR_SESSION, None)),
    # Flow reads/runs are org-scoped; project-scoped create is excepted above.
    ("deployment_flows.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    ("deployment_runs.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    # Sign-in admission administration (invites, identity links, auto-join
    # domain) governs who can enter the org → org admin, reads included
    # (invite listings expose member emails).
    ("identity.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    # GitHub Actions config uses the project's stored GitHub App auth against its repo →
    # project admin on the target project (writes); reads still need the target.
    ("github_actions.", AuthzSpec(PROJECT, PERM_PROJECT_ADMIN)),
    # Project-local install/refresh/uninstall write the caller's own checkout.
    ("project.install", AuthzSpec(CLIENT_LOCAL, None)),
    ("project.refresh", AuthzSpec(CLIENT_LOCAL, None)),
    ("project.uninstall", AuthzSpec(CLIENT_LOCAL, None)),
    ("harness.machine_report.", AuthzSpec(ACTOR_SESSION, None)),
    ("session_control.", AuthzSpec(ACTOR_SESSION, None)),
    # Steering acts on one project's own backlog and files launches against
    # it, so it is tenant content gated by that project's operator permission
    # — not the caller's own session. (`claims.steering.*` is a claim
    # operation and classifies under the `claims.` prefix instead.)
    ("steering.", AuthzSpec(PROJECT, PERM_ITEMS_WRITE)),
)



__all__ = ["AUTHZ_BY_PREFIX"]
