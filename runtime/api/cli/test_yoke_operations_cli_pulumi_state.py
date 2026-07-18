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
from yoke_cli.commands.adapters.projects_pulumi_state import (
    _read_checkpoint_operator_state,
)
from yoke_cli.commands.adapters import pulumi
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


def test_checkpoint_import_reads_0600_file_and_emits_only_receipt(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({
        "deployment": {"secrets_providers": {"state": {
            "url": "awskms://alias/yoke-pulumi",
            "encryptedkey": "encrypted-sensitive-material",
        }}}
    }))
    checkpoint.chmod(0o600)
    calls = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        calls.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"mode": "register", "receipt_digest": "receipt123"},
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
            "projects", "pulumi-state", "checkpoint-import",
            "--project", "yoke", "--stack", "yoke-platform-stage-vps",
            "--checkpoint-file", str(checkpoint),
        ])
    assert rc == 0
    assert stdout.getvalue() == "register|receipt123\n"
    assert "encrypted-sensitive-material" not in stdout.getvalue()
    assert calls[0].function == "projects.pulumi_state.checkpoint_import"
    assert calls[0].payload == {
        "project": "yoke",
        "stack_name": "yoke-platform-stage-vps",
        "secrets_provider": "awskms://alias/yoke-pulumi",
        "encrypted_key": "encrypted-sensitive-material",
        "apply": False,
    }


def test_checkpoint_import_refuses_readable_or_malformed_file(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text("{}")
    checkpoint.chmod(0o644)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = cli_main([
            "projects", "pulumi-state", "checkpoint-import",
            "--project", "yoke", "--stack", "stage",
            "--checkpoint-file", str(checkpoint),
        ])
    assert rc == 2
    assert "chmod 600" in stderr.getvalue()

    checkpoint.chmod(0o600)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = cli_main([
            "projects", "pulumi-state", "checkpoint-import",
            "--project", "yoke", "--stack", "stage",
            "--checkpoint-file", str(checkpoint),
        ])
    assert rc == 2
    assert "secrets-provider state" in stderr.getvalue()


def test_checkpoint_import_reads_backend_checkpoint_shape(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({
        "checkpoint": {"latest": {"secrets_providers": {"state": {
            "url": "awskms://alias/yoke-pulumi",
            "encryptedkey": "encrypted-sensitive-material",
        }}}}
    }))
    checkpoint.chmod(0o600)

    assert _read_checkpoint_operator_state(checkpoint) == (
        "awskms://alias/yoke-pulumi",
        "encrypted-sensitive-material",
    )


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
        patch(
            "yoke_cli.commands.adapters.projects_pulumi_stack_config."
            "load_pulumi_stack_config",
            return_value=payload,
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


def test_pulumi_exec_injects_machine_aws_and_transport_github_authority(
    monkeypatch,
):
    calls = {}
    machine_loader = object()
    github_loader = object()

    def execute(*args, **kwargs):
        calls["execute"] = (args, kwargs)
        return 0

    executor = type("Executor", (), {
        "aws_machine_capability_env": machine_loader,
        "execute_pulumi_command": staticmethod(execute),
    })
    renderer = type("Renderer", (), {
        "_resolve_project_root": staticmethod(lambda: "."),
    })
    monkeypatch.setattr(pulumi, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        pulumi,
        "build_pulumi_github_auth_loader",
        lambda **kwargs: github_loader,
    )
    monkeypatch.setattr(
        pulumi.importlib,
        "import_module",
        lambda name: (
            renderer if name.endswith("project_renderer_values") else executor
        ),
    )
    rc = pulumi.pulumi_exec([
        "--project", "platform", "--stack", "yoke-stage",
        "--bootstrap-local-authority", "--",
        "refresh", "--yes", "--non-interactive",
    ])
    assert rc == 0
    assert calls["execute"][1]["aws_env_loader"] is machine_loader
    assert calls["execute"][1]["github_auth_loader"] is github_loader
    assert calls["execute"][1]["bootstrap_local_authority"] is True
