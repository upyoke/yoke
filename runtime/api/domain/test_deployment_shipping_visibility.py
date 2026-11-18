"""Shared releases present only the records authorized for the reader."""

import json

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers.deployment_run_get import handle_deployment_run_get
from yoke_core.domain.handlers.deployment_runs import handle_deployment_run_list

RUN = "shared-visibility"
CANDIDATE = "candidate-visibility"
HIDDEN_TITLE = "Hidden project release member"


def _restricted_reader(conn):
    from runtime.api.domain.deployment_run_gates_test_support import seed_system_actor

    actor = seed_system_actor(conn, "shipping-restricted")
    conn.execute(
        "INSERT INTO actor_project_roles(actor_id,project_id,role_id,granted_at) "
        "SELECT %s,1,id,now() FROM roles WHERE name='owner'",
        (actor,),
    )
    conn.commit()
    return str(actor)


def _read_list(payload, actor):
    outcome = handle_deployment_run_list(
        deployment_request(
            function="deployment_runs.list", payload=payload, actor_id=actor
        )
    )
    assert outcome.primary_success, outcome.error
    return {row["id"]: row for row in outcome.result_payload["rows"]}


def _get(payload, actor, *, session_id="s-1"):
    request = deployment_request(
        function="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
        payload=payload,
        actor_id=actor,
    )
    request.actor.session_id = session_id
    outcome = handle_deployment_run_get(request)
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def test_shared_run_project_visibility(test_db):
    hidden = insert_item(
        test_db, id=30002, title=HIDDEN_TITLE, project="private-source"
    )
    hidden_project = int(hidden["project_id"])
    visible_removed = insert_item(test_db, id=30003)
    hidden_removed = insert_item(test_db, id=30004, project="private-source")
    stages = _stages(_plan(test_db, "member-visibility-check"))
    stages[0]["input_bindings"] = {
        "visible_input": {"project": "yoke", "branch": "main"},
        "hidden_input": {"project": "private-source", "branch": "main"},
    }
    _seed_run(
        test_db, run_id=RUN, stages=stages, members=(30001,), existing_members=(30002,)
    )
    projects = [
        {"project_id": 1, "project": "yoke", "commit_sha": "a" * 40},
        {
            "project_id": hidden_project,
            "project": "private-source",
            "commit_sha": "a" * 40,
        },
    ]
    sources = {
        "schema": 1,
        "projects": projects,
        "inputs": {"visible_input": "a" * 40, "hidden_input": "a" * 40},
        "preparation_receipt": {
            "members": [{"item_id": 30002, "public_ref": HIDDEN_TITLE}]
        },
    }
    contained = [
        {
            "id": item_id,
            "project_id": project_id,
            "merge_sha": "a" * 40,
            "state": "contained",
        }
        for item_id, project_id in ((30001, 1), (30002, hidden_project))
    ]
    removed = [
        {"item_id": int(item["id"]), "reason": "Item returned to work"}
        for item in (visible_removed, hidden_removed)
    ]
    carried = {
        "schema": 1,
        "items": [{"item_id": 30001, "project_id": 1}],
        "bound_projects": [
            {**projects[1], "items": [{"item_id": 30002, "title": HIDDEN_TITLE}]}
        ],
    }
    test_db.execute(
        "UPDATE deployment_runs SET bound_sources=%s,carried_work=%s,"
        "candidate_containment=%s,membership_removals=%s WHERE id=%s",
        (
            json.dumps(sources),
            json.dumps(carried),
            json.dumps({"answers": contained, "items": contained}),
            json.dumps(removed),
            RUN,
        ),
    )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at,carried_work,candidate_containment) "
        "SELECT %s,project_id,flow,status,created_at,carried_work,candidate_containment "
        "FROM deployment_runs WHERE id=%s",
        (CANDIDATE, RUN),
    )
    actor = _restricted_reader(test_db)

    for payload in ({"relevance": "overview"}, {"page": {"projects": ["yoke"]}}):
        all_rows = _read_list(payload, None)
        assert {item["id"] for item in all_rows[RUN]["member_items"]} == {30001, 30002}
        assert {item["id"] for item in all_rows[CANDIDATE]["contained_items"]} == {
            30001,
            30002,
        }
        rows = _read_list(payload, actor)
        (member,) = rows[RUN]["member_items"]
        assert member["id"] == 30001 and member["qa_obligations"] is not None
        assert [item["id"] for item in rows[RUN]["removed_member_items"]] == [30003]
        assert [item["id"] for item in rows[CANDIDATE]["contained_items"]] == [30001]
        assert rows[RUN]["bound_sources"] == {
            "schema": 1,
            "projects": projects[:1],
            "inputs": {"visible_input": "a" * 40},
        }
        assert rows[RUN]["carried_work"]["bound_projects"] == []
        if "relevance" in payload:
            assert member["item_qa"] is not None
            assert [item["id"] for item in rows[RUN]["delivery_candidate_items"]] == [
                30001
            ]
        else:
            assert _read_list({"page": {"search": HIDDEN_TITLE}}, actor) == {}
        assert HIDDEN_TITLE not in json.dumps(rows[RUN])

    detail = _get({}, actor)["run"]
    assert [item["id"] for item in detail["member_items"]] == [30001]
    assert [item["id"] for item in detail["membership_removals"]] == [30003]
    assert json.loads(detail["bound_sources"])["projects"] == projects[:1]
    assert "preparation_receipt" not in detail["bound_sources"]
    assert detail["carried_work"]["bound_projects"] == []
    assert json.loads(_get({"field": "bound_sources"}, actor)["value"]) == json.loads(
        detail["bound_sources"]
    )

    driver = _get(
        {"fields": ["bound_sources", "member_items"]}, actor, session_id=DRIVER_SESSION
    )["run"]
    assert json.loads(driver["bound_sources"]) == sources
    assert {item["id"] for item in driver["member_items"]} == {30001, 30002}

    test_db.execute(
        "UPDATE deployment_runs SET project_id=%s WHERE id=%s", (hidden_project, RUN)
    )
    test_db.commit()
    for payload in ({"relevance": "overview"}, {"page": {}}, {"summary": True}):
        row = _read_list(payload, actor)[RUN]
        assert row["release_lineage"] == ""
        assert row["project"] == ""
