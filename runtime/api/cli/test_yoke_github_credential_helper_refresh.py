"""Tests for `yoke github credential-helper refresh`."""

from __future__ import annotations

import json

from yoke_cli.commands.adapters import github_credential_helper as command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import github_git_credentials


def test_refresh_reports_true_when_a_prior_helper_was_republished(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_git_credentials, "refresh_installed_helper", lambda: True
    )

    assert command.github_credential_helper_refresh([]) == 0
    assert "Refreshed" in capsys.readouterr().out


def test_refresh_reports_false_when_nothing_was_installed(monkeypatch, capsys):
    monkeypatch.setattr(
        command.github_git_credentials, "refresh_installed_helper", lambda: False
    )

    assert command.github_credential_helper_refresh(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"refreshed": False}


def test_refresh_failure_is_reported_and_non_zero(monkeypatch, capsys):
    def raise_bundle_error():
        raise github_git_credentials.GitHubCredentialBundleError("disk full")

    monkeypatch.setattr(
        command.github_git_credentials, "refresh_installed_helper", raise_bundle_error
    )

    assert command.github_credential_helper_refresh(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"refreshed": False, "error": "disk full"}


def test_credential_helper_refresh_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["github", "credential-helper", "refresh", "--json"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is command.github_credential_helper_refresh
    assert remaining == ["--json"]
