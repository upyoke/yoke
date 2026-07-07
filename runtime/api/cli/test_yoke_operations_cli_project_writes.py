"""Dispatch tests for project write wrappers."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_operations_cli_projects import (
    _CAPTURED_REQUESTS,
    _run,
    _run_capture,
    _stub_ok,
)
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestProjectsCreateAndUpdate:
    def test_registry_maps_create_and_update_tokens(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[("projects", "create")][0] == "projects.create"
        assert SUBCOMMAND_REGISTRY[("projects", "update")][0] == "projects.update"

    def test_create_dispatches_project_metadata(self) -> None:
        rc = _run(
            _stub_ok, "projects", "create",
            "--slug", "demo",
            "--name", "Demo",
            "--org", "installer-e2e",
            "--project-id", "41",
            "--github-repo", "owner/demo",
            "--default-branch", "main",
            "--public-item-prefix", "DMO",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "projects.create"
        assert req.payload == {
            "slug": "demo",
            "name": "Demo",
            "org": "installer-e2e",
            "project_id": 41,
            "github_repo": "owner/demo",
            "default_branch": "main",
            "public_item_prefix": "DMO",
        }

    def test_update_dispatches_projects_update_function(self) -> None:
        rc = _run(
            _stub_ok, "projects", "update",
            "--slug", "demo", "--name", "Demo", "--github-repo", "owner/demo",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].function == "projects.update"

    def test_missing_slug_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "projects", "create",
            "--name", "Demo", "--github-repo", "owner/demo",
        )
        assert rc == 2


class TestProjectsCapabilitySecretSet:
    def test_registry_maps_tokens_to_function_id(self) -> None:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_ALIAS_REGISTRY,
            SUBCOMMAND_REGISTRY,
        )

        assert SUBCOMMAND_REGISTRY[("projects", "capability-secret", "set")][0] == (
            "projects.capability_secret.set"
        )
        assert SUBCOMMAND_ALIAS_REGISTRY[
            ("projects", "capability", "secret", "set")
        ][0] == "projects.capability_secret.set"

    def test_positional_secret_dispatches_without_printing_secret(self) -> None:
        secret = "ghp_project_runtime_secret"

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project": "demo",
                    "cap_type": "github",
                    "key": "token",
                    "source": "literal",
                    "stored": True,
                },
            )

        rc, out, err = _run_capture(
            stub,
            "projects", "capability", "secret", "set",
            "--project", "demo",
            "--cap-type", "github",
            "--key", "token",
            secret,
        )
        assert rc == 0
        assert secret not in out
        assert secret not in err
        assert _CAPTURED_REQUESTS[-1].function == "projects.capability_secret.set"
        assert _CAPTURED_REQUESTS[-1].payload == {
            "project": "demo",
            "cap_type": "github",
            "key": "token",
            "value": secret,
            "source": "literal",
        }

    def test_aws_secret_writes_machine_file_without_secret_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
        secret = "aws-secret-value"

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            assert secret not in repr(request.payload)
            if request.function == "projects.get":
                return FunctionCallResponse(
                    success=True,
                    function=request.function,
                    version=request.version,
                    request_id=request.request_id,
                    result={"project": "demo", "field": "slug", "value": "demo"},
                )
            assert request.function == "projects.capability_secret.set"
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project": "demo",
                    "cap_type": "aws-admin",
                    "key": "secret_access_key",
                    "source": "machine_file",
                    "stored": True,
                    "path": request.payload["path"],
                },
            )

        rc, out, err = _run_capture(
            stub,
            "projects", "capability", "secret", "set",
            "--project", "demo",
            "--cap-type", "aws-admin",
            "--key", "secret_access_key",
            secret,
        )

        assert rc == 0
        assert secret not in out
        assert secret not in err
        assert [req.function for req in _CAPTURED_REQUESTS] == [
            "projects.get",
            "projects.capability_secret.set",
        ]
        path = (
            tmp_path / "home" / "secrets" / "capability-secrets"
            / "demo" / "aws-admin" / "secret_access_key"
        )
        assert _CAPTURED_REQUESTS[-1].payload == {
            "project": "demo",
            "cap_type": "aws-admin",
            "key": "secret_access_key",
            "source": "machine_file",
            "path": str(path),
        }
        assert path.read_text(encoding="utf-8").strip() == secret
        assert path.stat().st_mode & 0o077 == 0

    def test_ssh_private_key_writes_machine_file_without_secret_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
        secret = "ssh-private-key"

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            assert secret not in repr(request.payload)
            if request.function == "projects.get":
                return FunctionCallResponse(
                    success=True,
                    function=request.function,
                    version=request.version,
                    request_id=request.request_id,
                    result={"project": "buzz", "field": "slug", "value": "buzz"},
                )
            assert request.function == "projects.capability_secret.set"
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={
                    "project": "buzz",
                    "cap_type": "ssh",
                    "key": "private_key",
                    "source": "machine_file",
                    "stored": True,
                    "path": request.payload["path"],
                },
            )

        rc, out, err = _run_capture(
            stub,
            "projects", "capability", "secret", "set",
            "--project", "buzz",
            "--cap-type", "ssh",
            "--key", "private_key",
            secret,
        )

        assert rc == 0
        assert secret not in out
        assert secret not in err
        assert [req.function for req in _CAPTURED_REQUESTS] == [
            "projects.get",
            "projects.capability_secret.set",
        ]
        path = (
            tmp_path / "home" / "secrets" / "capability-secrets"
            / "buzz" / "ssh" / "private_key"
        )
        assert _CAPTURED_REQUESTS[-1].payload == {
            "project": "buzz",
            "cap_type": "ssh",
            "key": "private_key",
            "source": "machine_file",
            "path": str(path),
        }
        assert path.read_text(encoding="utf-8").strip() == secret
        assert path.stat().st_mode & 0o077 == 0
