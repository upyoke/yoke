"""Secret-safe machine GitHub disconnect failure reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.test_github_app_machine_security import _configured_machine
from yoke_cli.config import github_git_credential_file, github_machine


def test_disconnect_sanitizes_outside_secrets_credential_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside" / "credential.json"
    config, _credential = _configured_machine(
        tmp_path,
        monkeypatch,
        credential_ref=outside,
    )

    report = github_machine.disconnect(config_path=config)
    rendered = github_machine.dumps_json(report)

    assert report["ok"] is True
    assert report["issues"][0]["code"] == "github_external_credential_left_untouched"
    assert str(outside) not in rendered
    assert outside.parent.exists() is False
    assert not config.exists()


def test_disconnect_sanitizes_unlink_failure_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, credential = _configured_machine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        github_git_credential_file,
        "delete_json_document",
        lambda path: (_ for _ in ()).throw(
            github_git_credential_file.CredentialFileError(
                f"unlink failed for {credential}"
            )
        ),
    )

    report = github_machine.disconnect(config_path=config)
    rendered = github_machine.dumps_json(report)

    assert report["ok"] is False
    assert report["issues"][0]["code"] == "github_credential_not_removed"
    assert str(credential) not in rendered
