"""Public chain reads include head diagnostics without changing JSON envelopes."""

import json

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_epic_review import _run_capture


@pytest.mark.parametrize("operation", ["get", "list"])
@pytest.mark.parametrize("decision", ["resumable", "busy", "blocked", "unknown"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_chain_read_output(operation, decision, json_mode):
    public_ref = "ITEM-" + str(42)
    result = {
        "epic_id": 42,
        "body": "existing|pipe|body",
        "head_dispatch": [
            {
                "task_num": 3,
                "decision": decision,
                "reason": "observed evidence",
                "holder_session_id": "holder",
            }
        ],
    }

    def stub(request):
        assert request.function == "workflow_item.epic_dispatch_chain." + operation
        assert request.actor.session_id == "test-session"
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    args = ["workflow-item", "epic-dispatch-chain", operation, "--epic", public_ref]
    if operation == "get":
        args += ["--worktree", "lane"]
    if json_mode:
        args.append("--json")
    rc, out, _err = _run_capture(stub, *args)
    assert rc == 0
    if json_mode:
        envelope = json.loads(out)
        assert envelope["success"] is True
        assert envelope["function"] == "workflow_item.epic_dispatch_chain." + operation
        assert envelope["result"] == {
            key: value for key, value in result.items() if key != "epic_id"
        }
    else:
        assert (
            out
            == f"existing|pipe|body\nhead task 3: {decision} — observed evidence; holder holder\n"
        )


@pytest.mark.parametrize(
    "heads",
    [
        None,
        [],
        [
            {
                "task_num": 3,
                "decision": "resumable",
                "reason": "no holder",
                "holder_session_id": None,
            }
        ],
    ],
)
def test_absent_diagnostics_and_holder_are_optional(heads):
    result = {"epic_id": 42, "body": "pipe"}
    if heads is not None:
        result["head_dispatch"] = heads

    def stub(request):
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    rc, out, _err = _run_capture(
        stub,
        "workflow-item",
        "epic-dispatch-chain",
        "list",
        "--epic",
        "ITEM-" + str(42),
    )
    assert rc == 0
    assert out == ("pipe\nhead task 3: resumable — no holder\n" if heads else "pipe\n")
