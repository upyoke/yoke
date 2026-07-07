"""Project identity resolution when slugs repeat across organizations."""

from __future__ import annotations

import pytest

from yoke_core.domain.org_schema import org_id_by_slug
from yoke_core.domain.project_identity import (
    AmbiguousProjectRefError,
    resolve_project,
)


def _insert_shared_slug_projects(conn) -> tuple[int, int, int]:
    default_org = org_id_by_slug(conn, "default")
    assert default_org is not None
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('other', 'Other Org', '2026-01-01T00:00:00Z') "
        "RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) "
        "VALUES "
        "(10, %s, 'shared', 'Default Shared', 'DEF', '2026-01-01T00:00:00Z'), "
        "(11, %s, 'shared', 'Other Shared', 'OTH', '2026-01-01T00:00:00Z')",
        (default_org, other_org),
    )
    conn.commit()
    return int(default_org), int(other_org), 11


def test_slug_resolves_inside_visible_project_set(test_db) -> None:
    _, _, visible_project = _insert_shared_slug_projects(test_db)

    ident = resolve_project(
        test_db, "shared", visible_project_ids={visible_project},
    )

    assert ident is not None
    assert ident.id == visible_project


def test_slug_ambiguity_requires_numeric_id_or_org(test_db) -> None:
    _, other_org, other_project = _insert_shared_slug_projects(test_db)

    with pytest.raises(AmbiguousProjectRefError):
        resolve_project(test_db, "shared", visible_project_ids={10, 11})

    ident = resolve_project(test_db, "shared", org=other_org)
    assert ident is not None
    assert ident.id == other_project
