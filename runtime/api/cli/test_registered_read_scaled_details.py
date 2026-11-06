"""Growing detail reads exercise their CLI adapters, not just their writers."""

import json
from unittest.mock import patch

from runtime.api.cli.registered_read_scale_test_support import command_for
from runtime.api.cli.test_machine_detail_render import detail as detail
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain.architecture_map_survey import propose_architecture_map


def run_read(function, args, result, capsys):
    route, adapter = command_for(function)
    response = FunctionCallResponse(
        success=True,
        function=function,
        version="v1",
        result=result,
    )
    with (
        read_output_scope(args, function, ("yoke", *route)),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch", return_value=response
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
    ):
        code = adapter(args)
    rendered = capsys.readouterr()
    assert code == 0, rendered.err
    assert not rendered.err
    return rendered.out


def test_machine_detail_adapter_bounds_large_native_models_and_sessions(
    request,
    capsys,
    monkeypatch,
):
    monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
    machine_detail = request.getfixturevalue("detail")
    function = "machine.detail"
    assert len(json.dumps(machine_detail).encode()) > REPLY_LIMIT_BYTES
    human = run_read(function, ["example-machine"], machine_detail, capsys)
    assert len(human.encode()) < REPLY_LIMIT_BYTES
    assert "256 models" in human
    assert "session-029" in human and "session-000" not in human
    whole = run_read(function, ["example-machine", "--full"], machine_detail, capsys)
    assert len(whole.encode()) > REPLY_LIMIT_BYTES
    assert "future-surface-model-255" in whole and "session-000" in whole
    machine = run_read(function, ["example-machine", "--json"], machine_detail, capsys)
    assert json.loads(machine)["result"] == machine_detail


def test_architecture_draft_adapter_bounds_large_scanned_inventory(capsys, monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
    paths = [
        f"packages/service/src/service/domain/{hint}_{index}.py"
        for hint in ("schema", "api", "plain")
        for index in range(600)
    ]
    assert len("\n".join(paths).encode()) > REPLY_LIMIT_BYTES
    draft = {"project_id": "example", **propose_architecture_map(paths)}
    function = "project_structure.architecture_draft.get"
    args = ["--project", "example"]
    human = run_read(function, args, draft, capsys)
    assert len(human.encode()) < REPLY_LIMIT_BYTES
    roots = draft["payload"]["domains"][0]["path_roots"]
    assert len(roots) <= 4
    assert all(root["glob"].rsplit("/", 1)[-1] in human for root in roots)
    assert all(note in human for note in draft["notes"])
    machine = run_read(function, [*args, "--json"], draft, capsys)
    assert json.loads(machine)["result"] == draft
