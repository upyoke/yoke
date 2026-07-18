"""Safe convergence coverage for code-owned deployment-flow successors."""

from __future__ import annotations

import json
from collections.abc import Mapping

from yoke_core.domain import deploy_defaults, flow_init
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.project_structure import create_project_structure_tables
from runtime.api.fixtures.backlog import insert_deployment_run, insert_item


_PROJECT = "externalwebapp"
_RELEASE_PREDECESSOR = "externalwebapp-previous-release"
_RELEASE_SUCCESSOR = "externalwebapp-production-release"
_HOTFIX_PREDECESSOR = "externalwebapp-previous-hotfix"
_HOTFIX_SUCCESSOR = "externalwebapp-production-hotfix"
_RELEASE_STAGES = json.dumps([
    {"kind": "migration_apply", "model_name": "primary",
     "lifecycle_phase": "implementing"},
    {"name": "merged", "executor": "auto"},
    {"name": "prod-deploy", "executor": "auto"},
    {"name": "smoke", "executor": "auto"},
    {"name": "complete", "executor": "auto"},
])
_HOTFIX_STAGES = json.dumps([
    {"kind": "migration_apply", "model_name": "primary",
     "lifecycle_phase": "implementing"},
    {"name": "merged", "executor": "auto"},
    {"name": "production-deploy", "executor": "auto"},
    {"name": "smoke", "executor": "auto"},
    {"name": "complete", "executor": "auto"},
])


def _definition(name: str, stages: str, done: str) -> dict[str, object]:
    return {
        "name": name,
        "description": f"Synthetic {name.lower()} definition",
        "stages": stages,
        "on_failure": "halt",
        "target_env": "production",
        "done_description": done,
    }


_RELEASE_DEFINITION = _definition(
    "Production Release", _RELEASE_STAGES, "Production release complete"
)
_HOTFIX_DEFINITION = _definition(
    "Production Hotfix", _HOTFIX_STAGES, "Production hotfix complete"
)
_RELEASE_PREDECESSOR_DEFINITION = _definition(
    "Legacy Production Release", _RELEASE_STAGES, "Production release complete"
)
_HOTFIX_PREDECESSOR_DEFINITION = _definition(
    "Legacy Production Hotfix", _HOTFIX_STAGES, "Production hotfix complete"
)
_TEST_FLOWS = (
    {
        "id": _RELEASE_SUCCESSOR,
        "project": _PROJECT,
        **_RELEASE_DEFINITION,
        "status": "active",
    },
    {
        "id": _HOTFIX_SUCCESSOR,
        "project": _PROJECT,
        **_HOTFIX_DEFINITION,
        "status": "active",
    },
)
_TEST_SUPERSESSIONS = (
    {
        "predecessor_id": _RELEASE_PREDECESSOR,
        "successor_id": _RELEASE_SUCCESSOR,
        "recognized_definitions": (_RELEASE_PREDECESSOR_DEFINITION,),
    },
    {
        "predecessor_id": _HOTFIX_PREDECESSOR,
        "successor_id": _HOTFIX_SUCCESSOR,
        "recognized_definitions": (_HOTFIX_PREDECESSOR_DEFINITION,),
    },
)


def _supersession(predecessor_id: str) -> Mapping[str, object]:
    return next(
        entry
        for entry in _TEST_SUPERSESSIONS
        if entry["predecessor_id"] == predecessor_id
    )


def _seed_catalog(conn, monkeypatch) -> None:
    seed_project_identities(conn)
    create_project_structure_tables(conn)
    conn.commit()
    monkeypatch.setattr(flow_init, "_SEED_FLOWS", _TEST_FLOWS)
    monkeypatch.setattr(
        flow_init, "BUILTIN_FLOW_SUPERSESSIONS", _TEST_SUPERSESSIONS
    )


def _insert_predecessor(conn, predecessor_id: str, definition_index: int = 0):
    spec = _supersession(predecessor_id)
    definition = spec["recognized_definitions"][definition_index]
    project_id = resolve_project_id(conn, "externalwebapp")
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


def test_terminal_run_history_is_preserved_and_default_moves(
    test_db, monkeypatch
) -> None:
    conn = test_db
    _seed_catalog(conn, monkeypatch)
    definition = _insert_predecessor(conn, _RELEASE_PREDECESSOR)
    insert_deployment_run(
        conn,
        id="run-terminal-history",
        project="externalwebapp",
        flow=_RELEASE_PREDECESSOR,
        status="succeeded",
        current_stage="complete",
    )
    deploy_defaults.set_default_flow(_PROJECT, _RELEASE_PREDECESSOR)

    flow_init.converge_flow_catalog(conn)
    flow_init.converge_flow_catalog(conn)

    predecessor = conn.execute(
        "SELECT stages, status FROM deployment_flows "
        "WHERE id=%s", (_RELEASE_PREDECESSOR,)
    ).fetchone()
    assert json.loads(predecessor[0]) == json.loads(definition["stages"])
    assert predecessor[1] == "disabled"
    assert conn.execute(
        "SELECT flow FROM deployment_runs WHERE id='run-terminal-history'"
    ).fetchone()[0] == _RELEASE_PREDECESSOR
    assert deploy_defaults.get_default_flow(_PROJECT) == _RELEASE_SUCCESSOR


def test_nonterminal_run_keeps_predecessor_active_for_resume(
    test_db, monkeypatch
) -> None:
    conn = test_db
    _seed_catalog(conn, monkeypatch)
    _insert_predecessor(conn, _RELEASE_PREDECESSOR)
    insert_deployment_run(
        conn,
        id="run-active-history",
        project="externalwebapp",
        flow=_RELEASE_PREDECESSOR,
        status="executing",
        current_stage="prod-deploy",
    )
    deploy_defaults.set_default_flow(_PROJECT, _RELEASE_PREDECESSOR)

    flow_init.converge_flow_catalog(conn)

    assert _flow_status(conn, _RELEASE_PREDECESSOR) == "active"
    assert deploy_defaults.get_default_flow(_PROJECT) == _RELEASE_SUCCESSOR


def test_terminal_item_reference_allows_hotfix_predecessor_retirement(
    test_db, monkeypatch,
) -> None:
    conn = test_db
    _seed_catalog(conn, monkeypatch)
    _insert_predecessor(conn, _HOTFIX_PREDECESSOR)
    insert_item(
        conn,
        id=901,
        project=_PROJECT,
        status="done",
        deployment_flow=_HOTFIX_PREDECESSOR,
    )

    flow_init.converge_flow_catalog(conn)

    assert _flow_status(conn, _HOTFIX_PREDECESSOR) == "disabled"
    assert conn.execute(
        "SELECT deployment_flow FROM items WHERE id=901"
    ).fetchone()[0] == _HOTFIX_PREDECESSOR
    successor_stages = json.loads(conn.execute(
        "SELECT stages FROM deployment_flows WHERE id=%s",
        (_HOTFIX_SUCCESSOR,),
    ).fetchone()[0])
    assert [stage.get("name", stage.get("kind")) for stage in successor_stages] == [
        "migration_apply",
        "merged",
        "production-deploy",
        "smoke",
        "complete",
    ]


def test_modified_predecessor_and_its_default_are_preserved(
    test_db, monkeypatch
) -> None:
    conn = test_db
    _seed_catalog(conn, monkeypatch)
    _insert_predecessor(conn, _HOTFIX_PREDECESSOR)
    conn.execute(
        "UPDATE deployment_flows SET description='Project-owned hotfix' "
        "WHERE id=%s", (_HOTFIX_PREDECESSOR,)
    )
    conn.commit()
    deploy_defaults.set_default_flow(_PROJECT, _HOTFIX_PREDECESSOR)

    flow_init.converge_flow_catalog(conn)

    assert _flow_status(conn, _HOTFIX_PREDECESSOR) == "active"
    assert deploy_defaults.get_default_flow(_PROJECT) == _HOTFIX_PREDECESSOR
    assert _flow_status(conn, _HOTFIX_SUCCESSOR) == "active"


def test_operator_disabled_successor_does_not_receive_new_defaults(
    test_db, monkeypatch,
) -> None:
    conn = test_db
    _seed_catalog(conn, monkeypatch)
    _insert_predecessor(conn, _RELEASE_PREDECESSOR)
    conn.execute(
        "UPDATE deployment_flows SET status='disabled' WHERE id=%s",
        (_RELEASE_SUCCESSOR,),
    )
    conn.commit()
    deploy_defaults.set_default_flow(_PROJECT, _RELEASE_PREDECESSOR)

    flow_init.converge_flow_catalog(conn)

    assert _flow_status(conn, _RELEASE_SUCCESSOR) == "disabled"
    assert _flow_status(conn, _RELEASE_PREDECESSOR) == "active"
    assert deploy_defaults.get_default_flow(_PROJECT) == _RELEASE_PREDECESSOR
