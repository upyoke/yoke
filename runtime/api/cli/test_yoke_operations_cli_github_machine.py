from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from runtime.api.cli.github_machine_test_helpers import (
    TOKEN,
    github_server,
    login,
    owner_logins,
    repo_full_names,
    requested_repo,
    scopes,
)

from yoke_cli import main as yoke_operations_cli


def test_github_machine_help_and_registry(capsys) -> None:
    # `yoke github connect` / `status` are machine-local GitHub credential
    # commands (local token file) with no dispatcher function
    # id, so they route via the tool-shaped table rather than
    # SUBCOMMAND_REGISTRY; HC-fallback-registry-coherence must not expect a
    # registered handler. See installer_local.TOOL_SHAPED_SUBCOMMANDS.
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("github", "connect") not in SUBCOMMAND_REGISTRY
    assert ("github", "status") not in SUBCOMMAND_REGISTRY
    assert ("github", "connect") in TOOL_SHAPED_SUBCOMMANDS
    assert ("github", "status") in TOOL_SHAPED_SUBCOMMANDS

    assert yoke_operations_cli.main(["github", "connect", "--help"]) == 0
    connect_out = capsys.readouterr().out
    assert "yoke github connect" in connect_out
    for flag in ("--api-url", "--config", "--json"):
        assert flag in connect_out
    for removed_flag in ("--token-file", "--token-stdin", "--github-repo"):
        assert removed_flag not in connect_out

    assert yoke_operations_cli.main(["github", "status", "--help"]) == 0
    status_out = capsys.readouterr().out
    assert "yoke github status" in status_out
    for flag in ("--config", "--api-url", "--offline", "--json"):
        assert flag in status_out
    assert "--github-repo" not in status_out


def test_github_connect_reports_browser_flow_unavailable_without_manual_token(
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
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["operation"] == "github.connect"
    assert payload["connection_model"] == "github_app"
    assert payload["configured"] is False
    assert payload["issues"][0]["code"] == "github_app_browser_flow_unavailable"
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


def test_github_status_reads_app_config_offline(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    refresh_file = tmp_path / "github.refresh"
    refresh_file.write_text("refresh-token\n", encoding="utf-8")
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "github": {
                    "api_url": "https://api.github.example",
                    "app_slug": "yoke-local",
                    "client_id": "Iv1.local",
                    "installations": [
                        {
                            "installation_id": 123,
                            "account_login": "octo-org",
                            "account_type": "Organization",
                            "repository_selection": "selected",
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
                        "permissions": {"issues": "write", "contents": "read"},
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
    assert payload["api_url"] == "https://api.github.example"
    assert payload["identity"]["checked"] is False
    assert payload["identity"]["login"] == "cached-user"
    assert payload["authorization"]["present"] is True
    assert payload["app"]["client_id"] == "Iv1.local"
    assert payload["access"]["owners"] == ["octo-org"]
    assert payload["access"]["repos"] == ["octo-org/app"]
    assert payload["permissions"]["ok"] is True
    assert payload["permissions"]["mode"] == "github_app"

    written_text = config.read_text(encoding="utf-8")
    _assert_token_absent("refresh-token", captured.out, captured.err, written_text)
    _assert_no_project_runtime_auth(json.loads(written_text))


def test_verify_scoped_token_result_carries_create_repos_capability() -> None:
    """A scope-bearing token with the repo scope reports create=True on the result."""
    from yoke_cli.config import github_machine_verify

    with github_server(expected_token=TOKEN) as server:
        result = github_machine_verify.verify(
            server.url, TOKEN, github_repo="machine-user/private-tool"
        )

    create = result["permissions"]["create_repos"]
    assert create["can_create"] is True
    assert create["create_private"] is True


def test_verify_scoped_token_no_repo_scope_reports_cannot_create() -> None:
    """A scope-bearing token missing the repo scope still fails the scope contract.

    The repo+workflow contract requires both, so a public_repo+workflow GitHub App user token is
    rejected before create-capability matters; but a repo-less GitHub App user token that DID
    satisfy the contract (repo present) is the only scoped_token case that reaches
    the create_repos derivation, so the create-False path is exercised directly
    through the classifier instead (see the contract suite). This test guards
    the contract-rejection wiring the create classifier sits behind.
    """
    from yoke_cli.config.github_machine_verify import (
        GitHubMachineVerificationError,
    )

    with github_server(
        expected_token=TOKEN, oauth_scopes="public_repo, workflow"
    ) as server:
        from yoke_cli.config import github_machine_verify

        try:
            github_machine_verify.verify(
                server.url, TOKEN, github_repo="machine-user/private-tool"
            )
        except GitHubMachineVerificationError as exc:
            assert "workflow" not in str(exc)  # workflow IS present here
            assert "repo" in str(exc)
        else:
            raise AssertionError("expected the missing-repo-scope contract error")


def test_verify_repository_token_result_carries_unknown_create_repos(monkeypatch) -> None:
    """A repository-scoped GitHub App user token reports create_repos.can_create is None (unknown)."""
    from yoke_cli.config import github_machine_repository_token
    from yoke_cli.config import github_machine_verify

    def _fake_read_access(api_url, token, identity, repo_full_name, *, request_json):
        return {
            "ok": True,
            "mode": "repository_token_non_mutating",
            "repo": repo_full_name,
            "summary": "non-mutating read checks passed",
        }

    monkeypatch.setattr(
        github_machine_repository_token, "verify_read_access", _fake_read_access
    )
    # No X-OAuth-Scopes header forces the repository-scoped branch.
    with github_server(expected_token=TOKEN, oauth_scopes="") as server:
        result = github_machine_verify.verify(
            server.url, TOKEN, github_repo="machine-user/private-tool"
        )

    create = result["permissions"]["create_repos"]
    assert create["can_create"] is None
    assert create["create_private"] is None
    assert create["basis"] == "repository_token_undetectable"


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
