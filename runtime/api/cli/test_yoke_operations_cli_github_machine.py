from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import github_git_credential_store
from yoke_contracts import github_app_installation_permissions

TOKEN = "manual-token-rejected-by-github-app-flow"


def test_github_machine_help_and_registry(capsys) -> None:
    # Machine-local commands have no dispatcher function id, so they route
    # through the tool-shaped table rather than
    # SUBCOMMAND_REGISTRY; HC-fallback-registry-coherence must not expect a
    # registered handler. See installer_local.TOOL_SHAPED_SUBCOMMANDS.
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("github", "connect") not in SUBCOMMAND_REGISTRY
    assert ("github", "status") not in SUBCOMMAND_REGISTRY
    assert ("github", "disconnect") not in SUBCOMMAND_REGISTRY
    assert ("github", "connect") in TOOL_SHAPED_SUBCOMMANDS
    assert ("github", "status") in TOOL_SHAPED_SUBCOMMANDS
    assert ("github", "disconnect") in TOOL_SHAPED_SUBCOMMANDS

    assert yoke_operations_cli.main(["github", "connect", "--help"]) == 0
    connect_out = capsys.readouterr().out
    assert "yoke github connect" in connect_out
    for flag in (
        "--client-id", "--app-slug", "--app-id", "--api-url", "--web-url",
        "--add-installation",
        "--config", "--json",
    ):
        assert flag in connect_out
    for removed_flag in ("--token-file", "--token-stdin", "--github-repo"):
        assert removed_flag not in connect_out

    assert yoke_operations_cli.main(["github", "status", "--help"]) == 0
    status_out = capsys.readouterr().out
    assert "yoke github status" in status_out
    for flag in ("--config", "--offline", "--json"):
        assert flag in status_out
    assert "--api-url" not in status_out
    assert "--github-repo" not in status_out

    assert yoke_operations_cli.main(["github", "disconnect", "--help"]) == 0
    disconnect_out = capsys.readouterr().out
    assert "yoke github disconnect" in disconnect_out
    assert "--config" in disconnect_out


def test_github_connect_requires_public_app_metadata_before_network_access(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"

    rc = yoke_operations_cli.main([
        "github",
        "connect",
        "--config",
        str(config),
        "--json",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "client id is required" in captured.err
    assert not config.exists()


def test_github_connect_rejects_manual_token_flags(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token_file = tmp_path / "github.pat"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")

    rc = yoke_operations_cli.main([
        "github",
        "connect",
        "--token-file",
        str(token_file),
        "--config",
        str(config),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert "--token-file" in captured.err
    assert not config.exists()


def test_github_connect_pending_installation_exits_zero(
    monkeypatch, capsys,
) -> None:
    from yoke_cli.commands.adapters import github as github_adapter

    monkeypatch.setattr(
        github_adapter.github_machine,
        "connect",
        lambda **kwargs: {
            "ok": True,
            "ready": False,
            "operation": "github.connect",
            "state": "pending_installation",
            "next_action": {
                "code": "install_github_app",
                "url": "https://github.com/apps/yoke/installations/new",
            },
            "issues": [{"severity": "warning", "code": "installation_required"}],
        },
    )

    rc = yoke_operations_cli.main([
        "github", "connect", "--client-id", "Iv1.local",
        "--app-slug", "yoke", "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert payload["state"] == "pending_installation"


def test_github_status_reads_app_config_offline(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    refresh_file = tmp_path / "github-app-user.json"
    github_git_credential_store.write_credential_document(refresh_file, {
        "schema_version": 1,
        "access_token": "access-token",
        "expires_at": "2027-07-09T17:00:00+00:00",
        "refresh_token": "refresh-token",
        "refresh_expires_at": "2027-12-09T17:00:00+00:00",
        "scope": "",
        "token_type": "bearer",
    })
    permissions = {
        item.key: item.access
        for item in github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "github": {
                    "api_url": "https://github.example/api/v3",
                    "web_url": "https://github.example",
                    "app_slug": "yoke-local",
                    "client_id": "Iv1.local",
                    "installations": [
                        {
                            "installation_id": 123,
                            "account_login": "octo-org",
                            "account_type": "Organization",
                            "repository_selection": "selected",
                            "permissions": permissions,
                        }
                    ],
                    "repositories": [
                        {"repository_id": 456, "full_name": "octo-org/app"},
                    ],
                    "authorization": {
                        "kind": "github_app_user_authorization",
                        "refresh_credential_ref": str(refresh_file),
                        "login": "cached-user",
                        "github_user_id": 42,
                        "status": "authorized",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    rc = yoke_operations_cli.main([
        "github",
        "status",
        "--config",
        str(config),
        "--offline",
        "--json",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["operation"] == "github.status"
    assert payload["connection_model"] == "github_app"
    assert payload["api_url"] == "https://github.example/api/v3"
    assert payload["identity"]["checked"] is False
    assert payload["identity"]["login"] == "cached-user"
    assert payload["authorization"]["present"] is True
    assert "kind" not in payload["authorization"]
    assert "refresh_credential_ref" not in payload["authorization"]
    assert str(refresh_file) not in captured.out
    assert payload["app"]["client_id"] == "Iv1.local"
    assert payload["access"]["owners"] == ["octo-org"]
    assert payload["access"]["repos"] == ["octo-org/app"]
    assert payload["permissions"]["ok"] is True
    assert payload["permissions"]["mode"] == "github_app_installation"
    assert payload["ready"] is True
    assert payload["access"]["snapshot_source"] == "cached"
    assert payload["access"]["repo_listing_ok"] is None

    written_text = config.read_text(encoding="utf-8")
    _assert_token_absent("refresh-token", captured.out, captured.err, written_text)
    _assert_no_project_runtime_auth(json.loads(written_text))


def _assert_token_absent(token: str, *texts: str) -> None:
    for text in texts:
        assert token not in text


def _assert_no_project_runtime_auth(payload: Mapping[str, Any]) -> None:
    for key in (
        "connections",
        "auth",
        "project_capabilities",
        "capability_secrets",
        "capabilities",
    ):
        assert key not in payload
