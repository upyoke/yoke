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
    for flag in (
        "--token-file",
        "--token-stdin",
        "--github-repo",
        "--api-url",
        "--config",
        "--json",
    ):
        assert flag in connect_out

    assert yoke_operations_cli.main(["github", "status", "--help"]) == 0
    status_out = capsys.readouterr().out
    assert "yoke github status" in status_out
    for flag in ("--config", "--github-repo", "--api-url", "--json"):
        assert flag in status_out


def test_github_connect_writes_metadata_without_token_or_runtime_auth(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token_file = tmp_path / "github.pat"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")

    with github_server(expected_token=TOKEN) as server:
        rc = yoke_operations_cli.main([
            "github",
            "connect",
            "--token-file",
            str(token_file),
            "--api-url",
            server.url,
            "--github-repo",
            "machine-user/private-tool",
            "--config",
            str(config),
            "--json",
        ])

    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["operation"] == "github.connect"
    assert login(payload) == "machine-user"
    assert {"read:org", "repo", "workflow"} <= scopes(payload)
    assert payload["permissions"]["ok"] is True
    assert payload["permissions"]["mode"] == "classic"
    assert {"machine-user", "octo-org"} <= owner_logins(payload)
    assert {
        "machine-user/private-tool",
        "octo-org/app",
    } <= repo_full_names(payload)
    assert requested_repo(payload)["full_name"] == "machine-user/private-tool"
    assert requested_repo(payload)["permissions"]["admin"] is True

    written_text = config.read_text(encoding="utf-8")
    _assert_token_absent(TOKEN, captured.out, captured.err, written_text)
    written = json.loads(written_text)
    github = written["github"]
    stored_token = tmp_path / "home" / "secrets" / "github.token"
    assert github["api_url"] == server.url
    assert github["credential_source"] == {
        "kind": "token_file",
        "path": str(stored_token),
    }
    assert stored_token.read_text(encoding="utf-8") == TOKEN + "\n"
    assert str(token_file) not in written_text
    assert github["verified_login"] == "machine-user"
    assert github["verified_user_id"] == 1001
    assert {"read:org", "repo", "workflow"} <= scopes(github)
    _assert_no_project_runtime_auth(written)


def test_github_connect_rejects_valid_pat_missing_required_scope(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token_file = tmp_path / "github.pat"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")

    with github_server(expected_token=TOKEN, oauth_scopes="repo, read:org") as server:
        rc = yoke_operations_cli.main([
            "github",
            "connect",
            "--token-file",
            str(token_file),
            "--api-url",
            server.url,
            "--config",
            str(config),
        ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "missing required classic PAT scope(s): workflow" in captured.err
    assert "Workflows: write" in captured.err
    assert not config.exists()


def test_github_status_reads_config_validates_online_and_does_not_leak_token(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token_file = tmp_path / "github.pat"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "github": {
                    "api_url": "https://stale.example.invalid",
                    "credential_source": {"kind": "token_file", "path": str(token_file)},
                    "verified_login": "cached-user",
                    "verified_user_id": 42,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with github_server(expected_token=TOKEN) as server:
        rc = yoke_operations_cli.main([
            "github",
            "status",
            "--config",
            str(config),
            "--api-url",
            server.url,
            "--github-repo",
            "machine-user/private-tool",
            "--json",
        ])

    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["operation"] == "github.status"
    assert payload["api_url"] == server.url
    assert login(payload) == "machine-user"
    assert {"read:org", "repo", "workflow"} <= scopes(payload)
    assert payload["permissions"]["ok"] is True
    assert payload["permissions"]["mode"] == "classic"
    assert {"machine-user", "octo-org"} <= owner_logins(payload)
    assert {
        "machine-user/private-tool",
        "octo-org/app",
    } <= repo_full_names(payload)
    assert requested_repo(payload)["full_name"] == "machine-user/private-tool"
    assert requested_repo(payload)["permissions"]["admin"] is True

    written_text = config.read_text(encoding="utf-8")
    _assert_token_absent(TOKEN, captured.out, captured.err, written_text)
    _assert_no_project_runtime_auth(json.loads(written_text))


def test_verify_classic_result_carries_create_repos_capability() -> None:
    """A classic PAT with the repo scope reports create=True on the result."""
    from yoke_cli.config import github_machine_verify

    with github_server(expected_token=TOKEN) as server:
        result = github_machine_verify.verify(
            server.url, TOKEN, github_repo="machine-user/private-tool"
        )

    create = result["permissions"]["create_repos"]
    assert create["can_create"] is True
    assert create["create_private"] is True


def test_verify_classic_no_repo_scope_reports_cannot_create() -> None:
    """A classic PAT missing the repo scope still fails the scope contract.

    The repo+workflow contract requires both, so a public_repo+workflow PAT is
    rejected before create-capability matters; but a repo-less PAT that DID
    satisfy the contract (repo present) is the only classic case that reaches
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


def test_verify_fine_grained_result_carries_unknown_create_repos(monkeypatch) -> None:
    """A fine-grained PAT reports create_repos.can_create is None (unknown)."""
    from yoke_cli.config import github_machine_fine_grained
    from yoke_cli.config import github_machine_verify

    def _fake_read_access(api_url, token, identity, repo_full_name, *, request_json):
        return {
            "ok": True,
            "mode": "fine_grained_non_mutating",
            "repo": repo_full_name,
            "summary": "non-mutating read checks passed",
        }

    monkeypatch.setattr(
        github_machine_fine_grained, "verify_read_access", _fake_read_access
    )
    # No X-OAuth-Scopes header forces the fine-grained branch.
    with github_server(expected_token=TOKEN, oauth_scopes="") as server:
        result = github_machine_verify.verify(
            server.url, TOKEN, github_repo="machine-user/private-tool"
        )

    create = result["permissions"]["create_repos"]
    assert create["can_create"] is None
    assert create["create_private"] is None
    assert create["basis"] == "fine_grained_undetectable"


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
