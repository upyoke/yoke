"""When creating release: itemless, project-scoped delivery at deployment-run creation."""

import io
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from runtime.api.execution_instruction_delivery_test_support import (
    conn as conn,
    seed as seed,
)
from runtime.api.workflow_execution_instruction_functions_test_support import _request
from yoke_core.domain import deployment_run_create_receipt as receipt
from yoke_core.domain import workflow_execution_instructions as domain
from yoke_core.domain.execution_instruction_delivery import InstructionDelivery
from yoke_core.domain.handlers import workflow_execution_instructions_crud as crud
from yoke_contracts.api.function_call import FunctionCallResponse

RELEASE_ONLY = dict(before_creation=False, on_every_read=False, when_creating_release=True)


def ids(rows):
    return [row["id"] for row in rows]


def scope(conn, identifier, *, workflows=(), all_workflows=False, projects=()):
    domain.set_instruction_scope(
        conn, identifier, workflow_ids=list(workflows),
        applies_to_all_workflows=all_workflows,
        applies_to_all_projects=False, project_ids=list(projects),
    )
    conn.commit()


@pytest.fixture
def release_conn(conn, monkeypatch):
    conn.execute("INSERT INTO projects VALUES (8, 'other', 'Other', 'main', 'OTH')")
    monkeypatch.setattr(receipt, "connect", lambda *a, **k: conn)
    return conn


def test_release_point_reaches_only_opted_in_project_instructions(release_conn):
    conn = release_conn
    opted = seed(conn, "Deploy stage and production together.", **RELEASE_ONLY)
    scope(conn, opted, workflows=["dash"], projects=[7])
    any_workflow = seed(conn, "Name the risk before staging first.", **RELEASE_ONLY)
    scope(conn, any_workflow, workflows=["issue"], projects=[7])
    seed(conn, "Item-only rule.")  # dash, all projects, not opted in
    elsewhere = seed(conn, "Other project's release rule.", **RELEASE_ONLY)
    scope(conn, elsewhere, all_workflows=True, projects=[8])
    unscoped = seed(conn, "Retired release rule.", **RELEASE_ONLY)
    scope(conn, unscoped, projects=[7])

    assert ids(receipt.release_instructions("acme")) == [opted, any_workflow]
    assert ids(receipt.release_instructions("other")) == [elsewhere]
    # Item-bound points never deliver a release-only instruction.
    assert opted not in ids(domain.resolve_for_item(conn, 51))
    assert opted not in ids(
        domain.resolve_execution_instructions(conn, workflow_id="dash", project_id=7)
    )


def test_release_point_is_set_cleared_and_counts_as_a_delivery_point(conn):
    identifier = seed(conn, "Release rule.", **RELEASE_ONLY)
    stored = domain.list_instructions(conn)[0]
    assert stored["when_creating_release"] is True
    assert stored["before_creation"] is False
    domain.update_instruction(
        conn, identifier, content="Release rule.",
        delivery={"before_creation": True, "when_creating_release": False},
    )
    assert domain.list_instructions(conn)[0]["when_creating_release"] is False
    with pytest.raises(ValidationError, match="When creating release"):
        InstructionDelivery(before_creation=False, on_every_read=False)
    assert InstructionDelivery().when_creating_release is False


def test_resolve_needs_no_workflow_for_the_release_point(release_conn):
    opted = seed(release_conn, "Release rule.", **RELEASE_ONLY)
    scope(release_conn, opted, workflows=["dash"], projects=[7])
    outcome = crud.handle_instruction_resolve(_request(
        "workflow.execution_instruction.resolve",
        {"project": "acme", "delivery_point": "when_creating_release"},
    ))
    served = outcome.result_payload["execution_instructions"]
    assert ids(served) == [opted]
    assert served[0]["read"] == (
        "yoke workflow execution-instruction resolve --project acme "
        "--delivery-point when_creating_release --full"
    )
    refused = crud.handle_instruction_resolve(_request(
        "workflow.execution_instruction.resolve", {"project": "acme"},
    ))
    assert not refused.primary_success
    assert "workflow_required" in str(refused.result_payload or refused)


def _created(run_id, instructions=None):
    result = {"run_id": run_id, "project": "acme", "flow": "stage", "status": "created"}
    if instructions is not None:
        result["execution_instructions"] = instructions
    return FunctionCallResponse(success=True, function="deployment_runs.create",
                                version="v1", request_id="r", result=result)


def test_cli_prints_release_instructions_once_and_tolerates_older_servers(monkeypatch):
    from yoke_cli.commands.adapters import deployment_run_create as create
    from yoke_cli.commands.adapters import deployment_run_create_set as release_set

    rule = [{"id": 199, "content": "Deploy stage and production together."}]
    stdout = io.StringIO()
    create.write_release_instructions(_created("a", rule).result, stdout)
    assert stdout.getvalue().count("Deploy stage and production together.") == 1
    older = io.StringIO()
    create.write_release_instructions(_created("a").result, older)
    assert older.getvalue() == ""

    responses = iter([_created("a", rule), _created("b", rule)])
    monkeypatch.setattr(release_set, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(release_set, "build_actor", lambda **k: None)
    monkeypatch.setattr(release_set, "creation_connection_error", lambda *a, **k: None)
    monkeypatch.setattr(release_set, "build_timeout_repeat", lambda *a: lambda r, _a: r)
    monkeypatch.setattr(release_set, "call_dispatcher", lambda **k: next(responses))
    printed = io.StringIO()

    def emit(response, *, json_mode, human_writer=None):
        human_writer(response, printed, io.StringIO())
        return 0

    monkeypatch.setattr(release_set, "emit_response", emit)
    receipts = []
    parsed = SimpleNamespace(session_id=None, project="acme", retry_of=None,
                             project_repo_path=None, idempotency_key="k", json_mode=False)
    payload = {"release_lineage": "abc"}
    assert release_set.create_release_set(
        parsed, ["stage", "production"], payload,
        lambda response, out, err: receipts.append(response.result["run_id"]),
    ) == 0
    assert printed.getvalue().count("Deploy stage and production together.") == 1
    assert receipts == ["a", "b"]
