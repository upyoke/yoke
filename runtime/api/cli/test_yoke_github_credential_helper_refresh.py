"""Tests for `yoke github credential-helper refresh`."""

from __future__ import annotations

import json

from yoke_cli.commands.adapters import github_credential_helper as command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


def test_refresh_reports_success_when_a_missing_bundle_is_rebuilt(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {"configured": True, "repaired": True},
    )

    assert command.github_credential_helper_refresh([]) == 0
    assert "Rebuilt" in capsys.readouterr().out


def test_refresh_reports_no_op_when_nothing_is_configured(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {"configured": False, "repaired": False},
    )

    assert command.github_credential_helper_refresh(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "configured": False,
        "repaired": False,
    }


def test_refresh_failure_is_reported_and_non_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {
            "configured": True,
            "repaired": False,
            "error": "disk full",
        },
    )

    assert command.github_credential_helper_refresh(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"configured": True, "repaired": False, "error": "disk full"}


def test_refresh_reports_an_inconclusive_result_as_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {
            "configured": None,
            "repaired": False,
            "error": "could not read git config for: /some/repo",
        },
    )

    assert command.github_credential_helper_refresh([]) == 1
    output = capsys.readouterr().out
    assert "credential helper repair failed" in output
    assert "/some/repo" in output


def test_credential_helper_refresh_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["github", "credential-helper", "refresh", "--json"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is command.github_credential_helper_refresh
    assert remaining == ["--json"]
