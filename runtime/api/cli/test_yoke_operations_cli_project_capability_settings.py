"""CLI envelope tests for project capability-settings functions."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str):
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"settings_json": '{"canonical":true}'},
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_get_dispatches_and_prints_exact_cas_base():
    rc, out, _err, calls = _run(
        "projects",
        "capability-settings",
        "get",
        "--project",
        "yoke",
        "--cap-type",
        "docker",
    )
    assert rc == 0
    assert out == '{"canonical":true}\n'
    assert calls[0].function == "projects.capability_settings.get"
    assert calls[0].payload == {"project": "yoke", "cap_type": "docker"}


def test_get_help_routes_pulumi_state_to_stack_scoped_reader():
    rc, out, err, calls = _run(
        "projects",
        "capability-settings",
        "get",
        "--help",
    )
    assert rc == 0
    help_text = out + err
    assert "pulumi-state reads are closed" in help_text
    assert "capability-settings merge" in help_text
    assert "yoke pulumi exec" in help_text
    assert "projects pulumi-stack-config get" in help_text
    assert calls == []


def test_get_refuses_pulumi_state_and_names_typed_bootstrap_path():
    rc, out, err, calls = _run(
        "projects",
        "capability-settings",
        "get",
        "--project",
        "externalwebapp",
        "--cap-type",
        "pulumi-state",
    )
    assert rc == 2
    assert out == ""
    assert calls == []
    assert "aggregate reads are closed" in err
    assert "capability-settings merge" in err
    assert "pulumi exec" in err
    assert "pulumi-stack-config get" in err


def test_set_carries_exact_base_and_document():
    rc, _out, _err, calls = _run(
        "projects",
        "capability-settings",
        "set",
        "--project",
        "yoke",
        "--cap-type",
        "docker",
        "--settings-json",
        '{"host":"new"}',
        "--base",
        '{"host":"old"}',
    )
    assert rc == 0
    assert calls[0].function == "projects.capability_settings.set"
    assert calls[0].payload == {
        "project": "yoke",
        "cap_type": "docker",
        "settings_json": '{"host":"new"}',
        "create": False,
        "base_settings_json": '{"host":"old"}',
    }


def test_merge_parses_json_values_and_raw_strings():
    rc, _out, _err, calls = _run(
        "projects",
        "capability-settings",
        "merge",
        "--project",
        "yoke",
        "--cap-type",
        "docker",
        "--set",
        "runtime.network=bridge",
        "--set",
        "registry=ecr",
    )
    assert rc == 0
    assert calls[0].function == "projects.capability_settings.merge"
    assert calls[0].payload["assignments"] == {
        "runtime.network": "bridge",
        "registry": "ecr",
    }


def test_remove_carries_exact_cas_base():
    rc, out, _err, calls = _run(
        "projects",
        "capability-settings",
        "remove",
        "--project",
        "platform",
        "--cap-type",
        "ephemeral-env",
        "--base",
        '{"trigger":"flow"}',
    )
    assert rc == 0
    assert out == '{"canonical":true}\n'
    assert calls[0].function == "projects.capability_settings.remove"
    assert calls[0].payload == {
        "project": "platform",
        "cap_type": "ephemeral-env",
        "base_settings_json": '{"trigger":"flow"}',
    }
