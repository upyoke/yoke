"""Safe convergence coverage for code-owned deployment-flow successors."""

from __future__ import annotations

import json
from collections.abc import Mapping

from yoke_core.domain import deploy_defaults
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_seed_data import (
    BUILTIN_FLOW_SUPERSESSIONS,
    BUZZ_PRODUCTION_HOTFIX_FLOW_ID,
    BUZZ_PRODUCTION_RELEASE_FLOW_ID,
)
from yoke_core.domain.flow_init import converge_flow_catalog
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.project_structure import create_project_structure_tables
from runtime.api.fixtures.backlog import insert_deployment_run, insert_item


def _supersession(predecessor_id: str) -> Mapping[str, object]:
    return next(
        entry
        for entry in BUILTIN_FLOW_SUPERSESSIONS
        if entry["predecessor_id"] == predecessor_id
    )


def _seed_catalog(conn) -> None:
    seed_project_identities(conn)
    create_project_structure_tables(conn)
    conn.commit()
    converge_flow_catalog(conn)


def _insert_predecessor(conn, predecessor_id: str, definition_index: int = 0):
    spec = _supersession(predecessor_id)
    definition = spec["recognized_definitions"][definition_index]
    project_id = resolve_project_id(conn, "buzz")
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, description, stages, on_failure, target_env, "
        "done_description, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)",
        (
            predecessor_id,
            project_id,
            definition["name"],
            definition["description"],
            definition["stages"],
            definition["on_failure"],
            definition["target_env"],
            definition["done_description"],
            iso8601_now(),
        ),
    )
    conn.commit()
    return definition


def _flow_status(conn, flow_id: str) -> str:
    return str(conn.execute(
        "SELECT status FROM deployment_flows WHERE id=%s", (flow_id,)
    ).fetchone()[0])


def test_terminal_run_history_is_preserved_and_default_moves(test_db) -> None:
    conn = test_db
    _seed_catalog(conn)
    definition = _insert_predecessor(conn, "buzz-prod-release", 1)
    insert_deployment_run(
        conn,
        id="run-terminal-history",
        project="buzz",
        flow="buzz-prod-release",
        status="succeeded",
        current_stage="complete",
    )
    deploy_defaults.set_default_flow("buzz", "buzz-prod-release")

    converge_flow_catalog(conn)
    converge_flow_catalog(conn)

    predecessor = conn.execute(
        "SELECT stages, status FROM deployment_flows "
        "WHERE id='buzz-prod-release'"
    ).fetchone()
    assert json.loads(predecessor[0]) == json.loads(definition["stages"])
    assert predecessor[1] == "disabled"
    assert conn.execute(
        "SELECT flow FROM deployment_runs WHERE id='run-terminal-history'"
    ).fetchone()[0] == "buzz-prod-release"
    assert deploy_defaults.get_default_flow("buzz") == (
        BUZZ_PRODUCTION_RELEASE_FLOW_ID
    )


def test_nonterminal_run_keeps_predecessor_active_for_resume(test_db) -> None:
    conn = test_db
    _seed_catalog(conn)
    _insert_predecessor(conn, "buzz-prod-release", 1)
    insert_deployment_run(
        conn,
        id="run-active-history",
        project="buzz",
        flow="buzz-prod-release",
        status="executing",
        current_stage="prod-deploy",
    )
    deploy_defaults.set_default_flow("buzz", "buzz-prod-release")

    converge_flow_catalog(conn)

    assert _flow_status(conn, "buzz-prod-release") == "active"
    assert deploy_defaults.get_default_flow("buzz") == (
        BUZZ_PRODUCTION_RELEASE_FLOW_ID
    )


def test_terminal_item_reference_allows_hotfix_predecessor_retirement(
    test_db,
) -> None:
    conn = test_db
    _seed_catalog(conn)
    _insert_predecessor(conn, "buzz-prod-hotfix", 1)
    insert_item(
        conn,
        id=901,
        project="buzz",
        status="done",
        deployment_flow="buzz-prod-hotfix",
    )

    converge_flow_catalog(conn)

    assert _flow_status(conn, "buzz-prod-hotfix") == "disabled"
    assert conn.execute(
        "SELECT deployment_flow FROM items WHERE id=901"
    ).fetchone()[0] == "buzz-prod-hotfix"
    successor_stages = json.loads(conn.execute(
        "SELECT stages FROM deployment_flows WHERE id=%s",
        (BUZZ_PRODUCTION_HOTFIX_FLOW_ID,),
    ).fetchone()[0])
    assert [stage.get("name", stage.get("kind")) for stage in successor_stages] == [
        "migration_apply",
        "merged",
        "production-deploy",
        "smoke",
        "complete",
    ]


def test_modified_predecessor_and_its_default_are_preserved(test_db) -> None:
    conn = test_db
    _seed_catalog(conn)
    _insert_predecessor(conn, "buzz-prod-hotfix")
    conn.execute(
        "UPDATE deployment_flows SET description='Project-owned hotfix' "
        "WHERE id='buzz-prod-hotfix'"
    )
    conn.commit()
    deploy_defaults.set_default_flow("buzz", "buzz-prod-hotfix")

    converge_flow_catalog(conn)

    assert _flow_status(conn, "buzz-prod-hotfix") == "active"
    assert deploy_defaults.get_default_flow("buzz") == "buzz-prod-hotfix"
    assert _flow_status(conn, BUZZ_PRODUCTION_HOTFIX_FLOW_ID) == "active"
