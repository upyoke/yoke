"""All registered list/report reads run against one fixed populated universe."""

from datetime import datetime, timezone
import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_epic_task,
    insert_item,
    seed_fixture_operating_actor,
)
from runtime.api.qa_catalog_test_support import create_release_readiness_plan
from runtime.api.steering_fleet_test_helpers import (
    STEERING_SESSION,
    seed_session,
    seed_steering_scope,
)
from runtime.api.tools.read_function_catalog import registered_read_ids
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import list_entries


def list_report_entries():
    reads = registered_read_ids()
    return [
        entry
        for entry in list_entries()
        if entry.function_id in reads
        and ("list" in entry.function_id.split(".") or ".report." in entry.function_id)
    ]


@pytest.fixture
def read_universe(test_db, tmp_path):
    seed_steering_scope(test_db)
    actor_id = seed_fixture_operating_actor(test_db)
    insert_item(test_db, id=99, workflow_id="epic")
    insert_epic_task(test_db, epic_id=99, task_num=1)
    create_release_readiness_plan(test_db)
    now = datetime.now(timezone.utc)
    test_db.execute(
        "INSERT INTO qa_plans(project_id,slug,name,description,created_at,updated_at) "
        "SELECT 1, 'output-' || n, 'Output ' || n, repeat('long description ', 1000), %s, %s "
        "FROM generate_series(1,60) AS n",
        (now, now),
    )
    for index in range(60):
        seed_session(test_db, f"output-session-{index}")
    test_db.execute(
        "UPDATE harness_sessions SET usage_totals=%s",
        (json.dumps({"status": "unavailable", "reason": "usage" * 1000}),),
    )
    test_db.execute("UPDATE harness_sessions SET actor_id=%s", (actor_id,))
    test_db.commit()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"connections": {}, "projects": {}}))
    return config, actor_id


@pytest.mark.parametrize(
    "entry", list_report_entries(), ids=lambda entry: entry.function_id
)
def test_default_read_outputs_fit_fixed_universe(entry, read_universe, capsys):
    fields = entry.request_model.model_fields
    payload = {"project": "yoke"} if "project" in fields else {}
    if "head_sha" in fields:
        payload["head_sha"] = "a" * 40
    if "config_path" in fields:
        payload["config_path"] = str(read_universe[0])
    kind = "global" if "global" in entry.target_kinds else entry.target_kinds[0]
    target = TargetRef.model_construct(
        kind=kind, project_id="1", item_id=99, epic_id=99, task_num=1
    )
    request = FunctionCallRequest(
        function=entry.function_id,
        actor=ActorContext(actor_id=str(read_universe[1]), session_id=STEERING_SESSION),
        target=target,
        payload=payload,
        options={"authorized_project_id": 1},
    )
    outcome = entry.handler(request)
    # A fixture without an external provider still exercises its diagnosed
    # refusal; data-owned reads must serve successful populated results.
    external = {
        "github.open_work.list",
        "github_actions.commit_runs.list",
        "test_machine.list",
        "packs.list",
    }
    if entry.function_id not in external:
        assert outcome.primary_success, outcome.error
    response = FunctionCallResponse(
        function=entry.function_id,
        version="v1",
        success=outcome.primary_success,
        result=outcome.result_payload,
        error=outcome.error,
    )
    for json_mode in (False, True):
        result = emit_response(response, json_mode=json_mode)
        rendered = capsys.readouterr()
        assert result == (0 if outcome.primary_success else 1), entry.function_id
        assert len((rendered.out + rendered.err).encode()) <= REPLY_LIMIT_BYTES


def test_size_gate_rejects_oversized_fixture(capsys):
    response = FunctionCallResponse(
        function="qa.plan.list",
        version="v1",
        success=True,
        result={"rows": [{"description": "x" * REPLY_LIMIT_BYTES}]},
    )
    assert emit_response(response, json_mode=True) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["success"] is True
    assert rendered["saved_response"]
