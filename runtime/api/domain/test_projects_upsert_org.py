"""Project upsert ownership-org behavior."""

from __future__ import annotations

from yoke_core.domain.org_schema import org_id_by_slug, seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.projects_upsert import cmd_upsert


def test_create_project_in_requested_org(test_db):
    conn = test_db
    seed_project_identities(conn)
    seed_default_org(conn)
    org_id = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("installer-e2e", "Installer E2E", "2026-01-01T00:00:00Z"),
    ).fetchone()[0]
    conn.commit()

    result = cmd_upsert(
        slug="installer-demo",
        name="Installer Demo",
        org="installer-e2e",
        github_repo="owner/installer-demo",
        mode="create",
    )

    assert result["created"] is True
    row = conn.execute(
        "SELECT org_id, github_repo FROM projects WHERE slug = %s",
        ("installer-demo",),
    ).fetchone()
    assert row[0] == org_id
    assert row[1] == "owner/installer-demo"
    capability_count = conn.execute(
        "SELECT COUNT(*) FROM project_capabilities c JOIN projects p "
        "ON p.id=c.project_id WHERE p.slug=%s AND c.type='github'",
        ("installer-demo",),
    ).fetchone()[0]
    assert capability_count == 0


def test_create_project_without_org_uses_default_org(test_db):
    conn = test_db
    seed_project_identities(conn)
    default_org_id = seed_default_org(conn)

    result = cmd_upsert(
        slug="default-org-create",
        name="Default Org Create",
        github_repo="owner/default-org-create",
        mode="create",
    )

    assert result["created"] is True
    row = conn.execute(
        "SELECT org_id FROM projects WHERE slug = %s",
        ("default-org-create",),
    ).fetchone()
    assert row[0] == default_org_id
    assert row[0] == org_id_by_slug(conn, "default")


def test_create_allows_same_slug_in_different_orgs(test_db):
    conn = test_db
    seed_project_identities(conn)
    seed_default_org(conn)
    conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES (%s, %s, %s)",
        ("other", "Other Org", "2026-01-01T00:00:00Z"),
    )
    conn.commit()

    first = cmd_upsert(
        slug="shared-create", name="Default Shared", org="default", mode="create",
    )
    second = cmd_upsert(
        slug="shared-create", name="Other Shared", org="other", mode="create",
    )

    assert first["created"] is True
    assert second["created"] is True
    rows = conn.execute(
        "SELECT org_id, name FROM projects WHERE slug=%s ORDER BY org_id",
        ("shared-create",),
    ).fetchall()
    assert [row["name"] for row in rows] == ["Default Shared", "Other Shared"]


def test_update_by_authorized_project_id_uses_that_org_scope(test_db):
    conn = test_db
    default_org = seed_default_org(conn)
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("other-update", "Other Update", "2026-01-01T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) VALUES "
        "(310, %s, 'shared-update', 'Default Shared', 'DSH', %s), "
        "(311, %s, 'shared-update', 'Other Shared', 'OSH', %s)",
        (
            default_org, "2026-01-01T00:00:00Z",
            other_org, "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()

    result = cmd_upsert(
        slug="shared-update",
        name="Other Shared Renamed",
        project_id=311,
        mode="update",
    )

    assert result["created"] is False
    rows = conn.execute(
        "SELECT id, name FROM projects WHERE slug=%s ORDER BY id",
        ("shared-update",),
    ).fetchall()
    assert [(row["id"], row["name"]) for row in rows] == [
        (310, "Default Shared"),
        (311, "Other Shared Renamed"),
    ]


def test_update_rejects_org_argument(test_db):
    conn = test_db
    seed_project_identities(conn)
    seed_default_org(conn)
    conn.commit()

    try:
        cmd_upsert(
            slug="yoke",
            name="Yoke",
            org="default",
            mode="update",
        )
    except ValueError as exc:
        assert "org is only valid" in str(exc)
    else:
        raise AssertionError("projects.update accepted org")
