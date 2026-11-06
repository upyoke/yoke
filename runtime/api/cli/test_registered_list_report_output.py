"""All registered list/report reads run against one fixed populated universe."""

from datetime import datetime, timezone
import json
from unittest.mock import patch

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
from runtime.api.cli.registered_read_scale_support import (
    command_for,
    parser_for,
    required_args,
    seed_growing_reads,
)
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
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
def read_universe(test_db, tmp_path, request):
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
    entry = getattr(request.node, "callspec", None)
    function = (
        entry.params["entry"].function_id if entry else "workflows.definition.get"
    )
    if (
        function.startswith(("projects.", "strategy.", "workflows.", "workflow."))
        or function == "deployment_flows.list"
    ):
        seed_growing_reads(test_db, now)
    test_db.commit()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"connections": {}, "projects": {}}))
    return config, actor_id


@pytest.mark.parametrize(
    "entry", list_report_entries(), ids=lambda entry: entry.function_id
)
def test_default_read_outputs_fit_fixed_universe(
    entry, read_universe, capsys, monkeypatch
):
    fields = entry.request_model.model_fields
    payload = {"project": "yoke"} if "project" in fields else {}
    if "project_id" in fields and fields["project_id"].is_required():
        payload["project_id"] = 1
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
    command = command_for(entry.function_id)
    if command is None:
        # Internal API reads have no CLI adapter; keep their envelope coverage.
        assert emit_response(response, json_mode=False) == (
            0 if outcome.primary_success else 1
        )
        rendered = capsys.readouterr()
        assert len((rendered.out + rendered.err).encode()) <= REPLY_LIMIT_BYTES
        return
    route, adapter = command
    parser = parser_for(entry.function_id, adapter, route)
    capsys.readouterr()
    assert parser is not None, entry.function_id
    args = required_args(parser)
    if entry.function_id == "items.dependency.list":
        args = ["--item", "TEST-99"]
    if entry.function_id == "decision_requests.list":
        args = ["--requesting-session", STEERING_SESSION]
    if "--config-path" in parser._option_string_actions:
        args.extend(["--config-path", str(read_universe[0])])
    monkeypatch.setenv("YOKE_SESSION_ID", STEERING_SESSION)
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
    for flags in ([], ["--json"]):
        calls = []

        def dispatch(request):
            calls.append(request.function)
            assert request.function == entry.function_id
            actual = entry.handler(
                request.model_copy(
                    update={
                        "actor": ActorContext(
                            actor_id=str(read_universe[1]), session_id=STEERING_SESSION
                        ),
                        "target": target,
                        "options": {"authorized_project_id": 1},
                    }
                )
            )
            return FunctionCallResponse(
                function=entry.function_id,
                version="v1",
                success=actual.primary_success,
                result=actual.result_payload,
                error=actual.error,
            )

        with (
            read_output_scope([*args, *flags], entry.function_id, ("yoke", *route)),
            patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=dispatch
            ),
            patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
            patch(
                "yoke_cli.commands.adapters.github_actions_commit_runs._call",
                side_effect=lambda name, payload, **kwargs: dispatch(request),
            ),
        ):
            result = adapter([*args, *flags])
        rendered = capsys.readouterr()
        assert entry.function_id in calls or entry.function_id == "env.list.run", (
            entry.function_id,
            rendered,
        )
        expected = (
            0
            if outcome.primary_success
            else (4 if entry.function_id == "github_actions.commit_runs.list" else 1)
        )
        assert result == expected, rendered
        if flags:
            assert isinstance(json.loads(rendered.out), dict)
        else:
            assert len((rendered.out + rendered.err).encode()) <= REPLY_LIMIT_BYTES


def test_oversized_json_fixture_keeps_selected_result(capsys):
    response = FunctionCallResponse(
        function="qa.plan.list",
        version="v1",
        success=True,
        result={"rows": [{"description": "x" * REPLY_LIMIT_BYTES}]},
    )
    assert emit_response(response, json_mode=True) == 0
    assert json.loads(capsys.readouterr().out)["result"] == response.result


def test_workflow_definition_scale_has_working_section_retry(
    read_universe, capsys, monkeypatch
):
    function = "workflows.definition.get"
    entry = next(entry for entry in list_entries() if entry.function_id == function)
    outcome = entry.handler(
        FunctionCallRequest(
            function=function,
            actor=ActorContext(
                actor_id=str(read_universe[1]), session_id=STEERING_SESSION
            ),
            target=TargetRef(kind="global"),
            payload={"project": "yoke"},
            options={"authorized_project_id": 1},
        )
    )
    assert outcome.primary_success, outcome.error
    response = FunctionCallResponse(
        function=function,
        version="v1",
        success=True,
        result=outcome.result_payload,
    )
    assert (
        len(json.dumps(response.model_dump(mode="json")).encode()) > REPLY_LIMIT_BYTES
    )
    route, adapter = command_for(function)
    monkeypatch.setenv("YOKE_SESSION_ID", STEERING_SESSION)
    for flags in ([], ["--section", "output-1"], ["--json"]):
        args = ["--project", "yoke", *flags]
        with (
            read_output_scope(args, function, ("yoke", *route)),
            patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                return_value=response,
            ),
            patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        ):
            code = adapter(args)
        rendered = capsys.readouterr()
        if not flags:
            assert code == 1
            assert not rendered.out
            assert "read_output_limit_exceeded" in rendered.err
            assert "--section output-1" in rendered.err
        elif flags[0] == "--section":
            assert code == 0, rendered.err
            assert "## output-1\n" in rendered.out
            assert "## output-2\n" not in rendered.out
            assert len(rendered.out.encode()) < REPLY_LIMIT_BYTES
        else:
            assert code == 0, rendered.err
            assert (
                json.loads(rendered.out)["result"]
                == response.model_dump(mode="json")["result"]
            )
