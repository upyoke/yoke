from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_cli import main as yoke_operations_cli

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
        "--client-id",
        "--app-slug",
        "--app-id",
        "--api-url",
        "--web-url",
        "--replace",
        "--add-installation",
        "--config",
        "--json",
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

    rc = yoke_operations_cli.main(
        [
            "github",
            "connect",
            "--config",
            str(config),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "selected Yoke connection is unavailable or invalid" in captured.err
    assert not config.exists()


def test_github_connect_rejects_manual_token_flags(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token_file = tmp_path / "github.pat"
    token_file.write_text(f"{TOKEN}\n", encoding="utf-8")

    rc = yoke_operations_cli.main(
        [
            "github",
            "connect",
            "--token-file",
            str(token_file),
            "--config",
            str(config),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "--token-file" in captured.err
    assert not config.exists()


def test_github_connect_pending_installation_exits_zero(
    monkeypatch,
    capsys,
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

    rc = yoke_operations_cli.main(
        [
            "github",
            "connect",
            "--client-id",
            "Iv1.local",
            "--app-slug",
            "yoke",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert payload["state"] == "pending_installation"


def test_plain_connect_selects_active_service_instead_of_environment(
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.commands.adapters import github as github_adapter

    monkeypatch.setenv("YOKE_GITHUB_APP_CLIENT_ID", "Iv1.hostile-env")
    monkeypatch.setattr(
        github_adapter.github_app_public_profile,
        "selected_https_service_api_url",
        lambda config_path=None: "https://yoke.team.example",
    )
    seen: dict[str, Any] = {}

    def connect(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "ready": False, "configured": True, "issues": []}

    monkeypatch.setattr(github_adapter.github_machine, "connect", connect)

    assert yoke_operations_cli.main(["github", "connect", "--json"]) == 0
    capsys.readouterr()
    assert seen["service_api_url"] == "https://yoke.team.example"
    assert seen["client_id"] is None


def test_plain_connect_reports_invalid_selection_without_starting_auth(
    monkeypatch,
    capsys,
) -> None:
    from yoke_cli.commands.adapters import github as github_adapter

    connect_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        github_adapter.github_app_public_profile,
        "selected_https_service_api_url",
        lambda config_path=None: (_ for _ in ()).throw(
            github_adapter.github_app_public_profile.GitHubAppPublicProfileError(
                "the selected Yoke connection is unavailable or invalid"
            )
        ),
    )
    monkeypatch.setattr(
        github_adapter.github_machine,
        "connect",
        lambda **kwargs: connect_calls.append(kwargs),
    )

    assert yoke_operations_cli.main(["github", "connect", "--json"]) == 1

    assert connect_calls == []
    error = capsys.readouterr().err
    assert "unavailable or invalid" in error
    assert "api.upyoke.com" not in error


def test_github_connect_retry_progress_explains_authorization_wait(capsys) -> None:
    from yoke_cli.commands.adapters import github as github_adapter

    github_adapter.setup_browser.render_progress(
        {
            "phase": "github_access_propagation_retry",
            "attempt": 2,
            "retry_in_seconds": 1.0,
        },
        json_mode=False,
    )

    assert capsys.readouterr().err == (
        "GitHub is finishing authorization; retrying the access check in 1s...\n"
    )


def test_github_connect_progress_neutralizes_terminal_controls(capsys) -> None:
    from yoke_cli.commands.adapters import github as github_adapter

    github_adapter.setup_browser.render_progress(
        {
            "phase": "device_authorization",
            "browser_action": github_adapter.setup_browser.action(
                "https://github.com/login/device\x1b]2;spoof\x07",
                "Approve access.",
                user_code="ABCD-EFGH\x9b31m",
            ),
        },
        json_mode=False,
    )

    rendered = capsys.readouterr().err
    assert "spoof" in rendered
    assert all(ord(char) >= 32 or char == "\n" for char in rendered)
