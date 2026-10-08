"""``auth`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic dicts into
the canonical ``CANONICAL_TABLES``). Holds the two-scope authorization surface:
the role/permission catalog and the org- and project-scoped grant tables.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


AUTH_TABLES: dict[str, dict] = {
    "frontend_event_rate_limits": {
        "columns": [
            ("client_key", "TEXT"),
            ("window_start", "INTEGER"),
            ("request_count", "INTEGER"),
        ],
        "notes": "Disposable shared anonymous collector request counters. client_key hashes trusted transport client identity and organization; counters are atomic and independent of events retention.",
    },
    "machine_authorization_rate_limits": {
        "columns": [
            ("client_key", "TEXT"),
            ("operation", "TEXT"),
            ("window_start", "INTEGER"),
            ("request_count", "INTEGER"),
        ],
        "notes": "Disposable per-client start and poll request counters shared across serving processes. The key hashes trusted transport identity; atomic counters bound unauthenticated machine sign-in traffic independently of telemetry.",
    },
    "machine_authorization_codes": {
        "columns": [
            ("device_hash", "TEXT"),
            ("user_code", "TEXT"),
            ("org_id", "INTEGER"),
            ("expires_at", "TIMESTAMPTZ"),
            ("actor_id", "INTEGER"),
            ("machine_id", "TEXT"),
            ("machine_name", "TEXT"),
            ("consumed_at", "TIMESTAMPTZ"),
            ("client_key", "TEXT"),
        ],
        "notes": "Self-host pending personal machine approval. Device secrets are hashed, raw credentials are never stored, and consumption is single-use. client_key hashes the trusted transport client identity for pending-code admission.",
    },
    "roles": {
        "columns": [
            ("id", "INTEGER"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Role catalog. Project roles: owner, operator, viewer, deployment_ci, "
            "and infrastructure_ci (granted via actor_project_roles). The deploy "
            "role can dispatch workflows, read their run/routing state, and "
            "record only capability-routed release pins; "
            "the infrastructure role carries only project.render.read. "
            "Neither carries project.install. Org roles: admin, operator, viewer, "
            "and migration_verification_ci (granted via actor_org_roles). A person "
            "holds exactly one org role from actor_role.HUMAN_ORG_ROLES (admin, "
            "operator, viewer), set with actors.role.set; operator at org scope "
            "is normal Yoke work across every project in the org. The narrow "
            "CI role can only compare candidate migration digests with the "
            "control-plane ledger. The all-access role is admin "
            "(renamed from the retired 'system'); it lives at org scope, never "
            "on a project, and carries every permission except the "
            "service-only hosted_service.deliver. Org role hosted_service is "
            "held only by the hosted service's own system actor (component "
            "hosted_service), granted by its token bootstrap, never by member "
            "grants or invites; it carries only hosted_service.deliver."
        ),
    },
    "permissions": {
        "columns": [
            ("id", "INTEGER"),
            ("key", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Permission catalog keyed by dotted key (items.read, claims.acquire, "
            "...). project.render.read belongs to infrastructure_ci; the "
            "three github_actions.* relay permissions and release_pin.record "
            "belong to deployment_ci. Org-scoped permissions are "
            "migration.content_identity.verify, project.create, "
            "hosted_service.deliver, and org.admin (renamed from the retired "
            "'system.admin'). They are never carried by a project role; only "
            "org roles hold them. hosted_service.deliver is service-only: no "
            "org-admin or project-owner wildcard carries it."
        ),
    },
    "role_permissions": {
        "columns": [
            ("role_id", "INTEGER"),
            ("permission_id", "INTEGER"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": "Role->permission catalog. Composite PK (role_id, permission_id).",
    },
    "actor_project_roles": {
        "columns": [
            ("actor_id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("role_id", "INTEGER"),
            ("granted_at", "TIMESTAMPTZ"),
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
            ("created_at", "TIMESTAMPTZ"),
            ("events_signing_key", "TEXT"),
        ],
        "notes": (
            "Instance/auth scope above projects. Every project belongs to exactly "
            "one org via projects.org_id; the seeded 'default' org owns all "
            "projects today."
            " events_signing_key is private server-owned attribution signing state, "
            "never public configuration. frontend_events_storage.collector_identity "
            "initializes it atomically; only its SHA-256 digest is publishable."
        ),
    },
    "actor_org_roles": {
        "columns": [
            ("actor_id", "INTEGER"),
            ("org_id", "INTEGER"),
            ("role_id", "INTEGER"),
            ("granted_at", "TIMESTAMPTZ"),
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
