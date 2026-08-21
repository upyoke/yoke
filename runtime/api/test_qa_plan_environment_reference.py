"""Site-qualified resolution of a QA plan's target environment."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_hosted_runtime_identity import (
    resolve_plan_environment_reference,
)
from yoke_core.domain.qa_plan_management import create_plan


def _two_sites_named_prod(conn) -> None:
    """Give the consumer project its own `prod` alongside the shared one.

    This is the live shape: a project's own site carries the deploy targets
    while the shared hosted runtime carries the targets its QA runs against,
    and both use the name `prod`.
    """
    conn.execute("UPDATE sites SET name='yoke' WHERE project_id=1")
    conn.execute(
        "INSERT INTO projects"
        "(id,slug,name,github_repo,public_item_prefix,org_id,created_at) "
        "VALUES (3,'platform','Platform','upyoke/platform','PLAT',1,"
        "'2026-01-01T00:00:00Z') ON CONFLICT(id) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES (3,'Yoke API','2026-01-01T00:00:00Z')"
    )
    for project_id, site_name in ((3, "Yoke API"), (1, "yoke")):
        conn.execute(
            "INSERT INTO environments(site,project_id,name,created_at) "
            "SELECT id,%s,'prod','2026-01-01T00:00:00Z' FROM sites "
            "WHERE project_id=%s AND name=%s",
            (project_id, project_id, site_name),
        )


def _environment_id(conn, *, site_name: str) -> int:
    row = conn.execute(
        "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
        "WHERE s.name=%s AND e.name='prod'",
        (site_name,),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def test_bare_name_resolves_within_the_shared_hosted_runtime() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)

        target = resolve_plan_environment_reference(
            conn, plan_project_id=1, environment="prod"
        )

        assert target["site_name"] == "Yoke API"
        assert target["environment_id"] == _environment_id(
            conn, site_name="Yoke API"
        )


def test_site_qualified_reference_selects_the_projects_own_target() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)

        target = resolve_plan_environment_reference(
            conn, plan_project_id=1, environment="yoke/prod"
        )

        assert target["site_name"] == "yoke"
        assert target["environment_id"] == _environment_id(conn, site_name="yoke")


def test_environment_id_reference_selects_that_exact_row() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)
        own = _environment_id(conn, site_name="yoke")

        target = resolve_plan_environment_reference(
            conn, plan_project_id=1, environment=str(own)
        )

        assert target["environment_id"] == own
        assert target["site_name"] == "yoke"


def test_unregistered_reference_names_every_candidate_with_its_site() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)

        with pytest.raises(ValueError) as caught:
            resolve_plan_environment_reference(
                conn, plan_project_id=1, environment="yoke/nope"
            )

        message = str(caught.value)
        assert "Yoke API/prod" in message
        assert "yoke/prod" in message


def test_unregistered_environment_id_is_refused() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)

        with pytest.raises(ValueError, match="environment id 99999"):
            resolve_plan_environment_reference(
                conn, plan_project_id=1, environment="99999"
            )


def test_single_site_project_resolves_a_bare_name_within_that_site() -> None:
    with test_database() as conn:
        target = resolve_plan_environment_reference(
            conn, plan_project_id=2, environment="development"
        )

        assert target["site_name"] == "External webapp API"
        assert target["environment_name"] == "development"


def test_plan_create_stores_the_site_qualified_target() -> None:
    with test_database() as conn:
        _two_sites_named_prod(conn)
        own = _environment_id(conn, site_name="yoke")

        plan = create_plan(
            conn,
            project="yoke",
            slug="site-qualified-plan",
            target_environment="yoke/prod",
        )

        stored = conn.execute(
            "SELECT target_environment_id FROM qa_plans WHERE id=%s",
            (int(plan["id"]),),
        ).fetchone()
        assert int(
            stored["target_environment_id"]
            if hasattr(stored, "keys")
            else stored[0]
        ) == own
