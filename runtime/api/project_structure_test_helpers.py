"""Shared project-structure test helpers."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect


def seed_project(
    path: str,
    project_id: int,
    slug: str,
    name: Optional[str] = None,
    *,
    github_repo: Optional[str] = None,
    public_item_prefix: str = "YOK",
) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, github_repo, public_item_prefix, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                github_repo = EXCLUDED.github_repo,
                public_item_prefix = EXCLUDED.public_item_prefix
            """,
            (
                project_id,
                slug,
                name or slug.title(),
                github_repo,
                public_item_prefix,
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
