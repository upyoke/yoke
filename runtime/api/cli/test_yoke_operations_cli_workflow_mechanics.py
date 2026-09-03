"""CLI envelope coverage for workflow mechanics and Test Mac."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_cli.main import main as cli_main


def _run(*argv: str) -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = cli_main(list(argv))
    assert captured
    return result, captured[-1]


def test_registry_exposes_mechanics_and_test_machine_functions() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli import operation_inventory

    expected = {
        ("workflows", "mechanics", "get"): "workflows.mechanics.get",
        (
            "workflows",
            "testing-default",
            "set",
        ): "workflows.testing_default.set",
        (
            "workflows",
            "delivery-default",
            "set",
        ): "workflows.delivery_default.set",
        (
            "workflows",
            "approval-defaults",
            "publish",
        ): "workflows.approval_defaults.publish",
        ("test-machine", "list"): "test_machine.list",
        ("test-machine", "get"): "test_machine.get",
        (
            "test-machine",
            "settings-replace",
        ): "test_machine.settings_replace",
        ("test-machine", "verify"): "test_machine.verify",
    }
    for tokens, function_id in expected.items():
        assert SUBCOMMAND_REGISTRY[tokens][0] == function_id
        inventory_entry = operation_inventory.lookup("yoke " + " ".join(tokens))
        assert inventory_entry is not None
        assert inventory_entry.status == operation_inventory.WRAPPED


def test_mechanics_get_dispatches_empty_global_payload() -> None:
    result, request = _run("workflows", "mechanics", "get")

    assert result == 0
    assert request.function == "workflows.mechanics.get"
    assert request.target.kind == "global"
    assert request.payload == {}


def test_testing_default_dispatches_typed_project_binding() -> None:
    result, request = _run(
        "workflows",
        "testing-default",
        "set",
        "--project",
        "yoke",
        "--workflow",
        "issue",
        "--plan-id",
        "17",
        "--apply-to-all",
    )

    assert result == 0
    assert request.function == "workflows.testing_default.set"
    assert request.payload == {
        "project": "yoke",
        "workflow_id": "issue",
        "plan_id": 17,
        "apply_to_all": True,
    }


def test_delivery_default_dispatches_typed_project_binding() -> None:
    result, request = _run(
        "workflows",
        "delivery-default",
        "set",
        "--project",
        "yoke",
        "--workflow",
        "dash",
        "--flow",
        "yoke-production",
    )

    assert result == 0
    assert request.function == "workflows.delivery_default.set"
    assert request.payload == {
        "project": "yoke",
        "workflow_id": "dash",
        "flow_id": "yoke-production",
        "apply_to_all": False,
    }


def test_approval_publish_reads_bounded_defaults_document(tmp_path) -> None:
    defaults_file = tmp_path / "approval-defaults.json"
    defaults_file.write_text(
        json.dumps(
            {
                "done": {"roles": ["owner"], "actors": [2]},
            }
        ),
        encoding="utf-8",
    )

    result, request = _run(
        "workflows",
        "approval-defaults",
        "publish",
        "--workflow",
        "issue",
        "--expected-current-version",
        "3",
        "--defaults-file",
        str(defaults_file),
    )

    assert result == 0
    assert request.function == "workflows.approval_defaults.publish"
    assert request.payload == {
        "workflow_id": "issue",
        "expected_current_version": 3,
        "approval_defaults": {
            "done": {"roles": ["owner"], "actors": [2]},
        },
    }


def test_test_machine_commands_dispatch_the_machine_selector(tmp_path) -> None:
    result, request = _run(
        "test-machine",
        "list",
        "--project",
        "yoke",
    )
    assert result == 0
    assert request.function == "test_machine.list"
    assert request.payload == {"project": "yoke"}

    result, request = _run(
        "test-machine",
        "get",
        "--project",
        "yoke",
        "--machine",
        "mac-mini-lab",
    )
    assert result == 0
    assert request.payload == {
        "project": "yoke",
        "machine": "mac-mini-lab",
    }

    settings_file = tmp_path / "test-machine.json"
    settings = {
        "resource_name": "mac-mini-lab",
        "host": "test-mac.local",
        "user": "yoke-test",
        "host_kind": "mac-ssh",
        "operating_notes": "",
    }
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    result, request = _run(
        "test-machine",
        "settings-replace",
        "--project",
        "yoke",
        "--machine",
        "mac-mini-lab",
        "--settings-file",
        str(settings_file),
        "--new",
    )
    assert result == 0
    assert request.payload == {
        "project": "yoke",
        "machine": "mac-mini-lab",
        "settings": settings,
        "base_settings": None,
    }
