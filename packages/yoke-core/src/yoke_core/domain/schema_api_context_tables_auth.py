"""``auth`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic dicts into
the canonical ``CANONICAL_TABLES``). Holds the two-scope authorization surface:
the role/permission catalog and the org- and project-scoped grant tables.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


AUTH_TABLES: dict[str, dict] = {
    "roles": {
        "columns": [
            ("id", "INTEGER"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Role catalog. Project roles: owner, operator, viewer, deployment_ci, "
            "and infrastructure_ci (granted via actor_project_roles). The deploy "
            "role can dispatch workflows and read their run/routing state only; "
            "the infrastructure role carries project.render.read plus narrow "
            "runner-token issuance. Neither carries project.install. Org roles: admin, "
            "viewer (granted via actor_org_roles). The all-access role is admin "
            "(renamed from the retired 'system'); it lives at org scope, never "
            "on a project."
        ),
    },
    "permissions": {
        "columns": [
            ("id", "INTEGER"),
            ("key", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Permission catalog keyed by dotted key (items.read, claims.acquire, "
            "...). project.render.read and runner_fleet.token.issue belong to "
            "infrastructure_ci; the three github_actions.* relay permissions "
            "belong to deployment_ci. Org-scoped permissions org.admin "
            "(renamed from the retired "
            "'system.admin') and project.create are never carried by a project "
            "role — only the org admin role holds them."
        ),
    },
    "role_permissions": {
        "columns": [
            ("role_id", "INTEGER"),
            ("permission_id", "INTEGER"),
            ("created_at", "TEXT"),
        ],
        "notes": "Role->permission catalog. Composite PK (role_id, permission_id).",
    },
    "actor_project_roles": {
        "columns": [
            ("actor_id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("role_id", "INTEGER"),
            ("granted_at", "TEXT"),
            ("granted_by_actor_id", "INTEGER"),
        ],
        "notes": (
            "Project-scoped grants: a role applies only to that one project. "
            "Composite PK (actor_id, project_id, role_id)."
        ),
    },
    "organizations": {
        "columns": [
            ("id", "INTEGER"),
            ("slug", "TEXT"),
            ("name", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Instance/auth scope above projects. Every project belongs to exactly "
            "one org via projects.org_id; the seeded 'default' org owns all "
            "projects today."
        ),
    },
    "actor_org_roles": {
        "columns": [
            ("actor_id", "INTEGER"),
            ("org_id", "INTEGER"),
            ("role_id", "INTEGER"),
            ("granted_at", "TEXT"),
            ("granted_by_actor_id", "INTEGER"),
        ],
        "notes": (
            "Org-scoped grants. permission_decision resolves org scope THEN "
            "project scope: an org admin grant on a project's owning org implies "
            "every permission on every project in that org; a project grant "
            "applies to that one project; allowed if either scope carries it. "
            "Composite PK (actor_id, org_id, role_id)."
        ),
    },
}


__all__ = ["AUTH_TABLES"]
