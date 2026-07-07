"""Baseline project-identity rows for test fixtures.

The production bootstrap seeds no project rows — a fresh universe starts
with an empty ``projects`` table and projects enter through onboarding
(``yoke project install`` / ``projects_upsert``). Test databases, however,
share a two-project baseline so fixtures, helpers, and assertions agree on
one identity map: :data:`SEED_PROJECT_IDS` below — slug ``yoke``
(the control-plane project) and slug ``buzz`` (a managed webapp project).

Test-fixture surface only; production init chains must not import it.
"""

from __future__ import annotations

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import DEFAULT_PUBLIC_ITEM_PREFIX

#: Fixture project-identity map shared by test databases. Production
#: tables carry no baseline rows, so these ids exist only where a test
#: helper seeds them.
SEED_PROJECT_IDS = {
    "yoke": 1,
    "buzz": 2,
}


def seed_project_identities(conn) -> None:
    """Seed the two baseline test-project identity rows (idempotent)."""
    p = "%s" if connection_is_postgres(conn) else "?"
    rows = (
        (SEED_PROJECT_IDS["yoke"], "yoke", "Yoke", "🐂", "upyoke/yoke", DEFAULT_PUBLIC_ITEM_PREFIX),
        (SEED_PROJECT_IDS["buzz"], "buzz", "Buzz", "\U0001f41d", "example-org/buzz", "BUZ"),
    )
    for project_id, slug, name, emoji, github_repo, prefix in rows:
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, emoji, github_repo, public_item_prefix, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) ON CONFLICT(id) DO NOTHING",
            (project_id, slug, name, emoji, github_repo, prefix, iso8601_now()),
        )
        conn.execute(
            f"UPDATE projects SET emoji={p} "
            f"WHERE id={p} AND (emoji IS NULL OR emoji='')",
            (emoji, project_id),
        )
        conn.execute(
            f"UPDATE projects SET github_repo={p} "
            f"WHERE id={p} AND (github_repo IS NULL OR github_repo='')",
            (github_repo, project_id),
        )
    conn.commit()


def seed_buzz_site_environments(conn) -> None:
    """Seed one site with two environments for the buzz test project."""
    p = "%s" if connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}) ON CONFLICT(id) DO NOTHING",
        ("buzz-web", SEED_PROJECT_IDS["buzz"], "Buzz Web", iso8601_now()),
    )
    for env_id, env_name in (
        ("buzz-web-production", "production"),
        ("buzz-web-staging", "staging"),
    ):
        conn.execute(
            "INSERT INTO environments (id, site, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) ON CONFLICT(id) DO NOTHING",
            (env_id, "buzz-web", env_name, iso8601_now()),
        )
    conn.commit()


__all__ = [
    "SEED_PROJECT_IDS",
    "seed_buzz_site_environments",
    "seed_project_identities",
]
