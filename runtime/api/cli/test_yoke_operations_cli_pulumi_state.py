"""CLI boundary tests for Pulumi state and stack config surfaces."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import stat
from unittest.mock import patch

from yoke_cli.commands.adapters.projects_pulumi_stack_config import (
    projects_pulumi_stack_config_get,
)
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def test_migration_adapter_dispatches_exact_stack_set_and_dry_run():
    calls = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        calls.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"mode": "migrate", "receipt_digest": "abc123"},
        )

    stdout = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
    ):
        rc = cli_main([
            "projects", "pulumi-state", "migrate", "--project", "yoke",
            "--site-id", "main", "--stack", "yoke-infra", "--stack",
            "yoke-vps",
        ])
    assert rc == 0
    assert stdout.getvalue() == "migrate|abc123\n"
    assert calls[0].function == "projects.pulumi_state.migrate"
    assert calls[0].payload == {
        "project": "yoke",
        "site_id": "main",
        "stack_names": ["yoke-infra", "yoke-vps"],
        "apply": False,
    }


def test_stack_config_adapter_writes_0600_without_body_output(tmp_path):
    output = tmp_path / "stack.json"
    payload = {
        "config_schema": 2,
        "project_id": 1,
        "project_slug": "yoke",
        "stack_name": "yoke-infra",
        "stack_kind": "infra",
        "render_values": {},
        "operator_state": {
            "secrets_provider": "provider-sensitive",
            "encrypted_key": "key-sensitive",
        },
        "authority": {"sensitive_paths": ["operator_state.encrypted_key"]},
    }
    response = FunctionCallResponse(
        success=True,
        function="projects.pulumi_stack_config.get",
        version="v1",
        request_id="request",
        result=payload,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch(
            "yoke_cli.commands.adapters.projects_pulumi_stack_config."
            "ensure_handlers_loaded"
        ),
        patch(
            "yoke_cli.commands.adapters.projects_pulumi_stack_config."
            "call_dispatcher",
            return_value=response,
        ),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = projects_pulumi_stack_config_get([
            "--project", "yoke", "--stack", "yoke-infra", "--output",
            str(output),
        ])
    assert rc == 0
    assert json.loads(output.read_text()) == payload
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "provider-sensitive" not in stdout.getvalue()
    assert "key-sensitive" not in stdout.getvalue()
    path, byte_count, digest = stdout.getvalue().strip().split("|")
    assert Path(path) == output
    assert int(byte_count) == output.stat().st_size
    assert len(digest) == 64


def test_stack_config_adapter_refuses_overwrite_before_fetch(tmp_path):
    output = tmp_path / "stack.json"
    output.write_text("existing")
    with patch(
        "yoke_cli.commands.adapters.projects_pulumi_stack_config.call_dispatcher"
    ) as dispatcher:
        rc = projects_pulumi_stack_config_get([
            "--project", "yoke", "--stack", "yoke-infra", "--output",
            str(output),
        ])
    assert rc == 2
    dispatcher.assert_not_called()
    assert output.read_text() == "existing"
