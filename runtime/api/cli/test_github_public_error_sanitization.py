from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from runtime.api.cli.test_github_app_machine_connection import _device_opener
from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_machine
from yoke_cli.config import github_user_tokens


SECRET_PATH = "/private/secrets/github-app-user.json"


def test_git_credential_helper_sanitizes_store_error(
    monkeypatch, capsys,
) -> None:
    store = github_git_credential_helper.credential_store
    monkeypatch.setattr(
        store,
        "load_config",
        lambda path: (_ for _ in ()).throw(
            store.GitHubCredentialStoreError(f"missing {SECRET_PATH}")
        ),
    )

    rc = github_git_credential_helper.main(
        ["--config", "/machine/config.json", "get"],
        stdin=StringIO("protocol=https\nhost=github.com\n\n"),
        stdout=StringIO(),
    )

    error = capsys.readouterr().err
    assert rc == 1
    assert SECRET_PATH not in error
    assert "yoke github status" in error
    assert "yoke github connect" in error


def test_connect_sanitizes_initial_credential_save_error(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        github_machine.github_user_tokens,
        "store_initial_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            github_user_tokens.GitHubUserTokenError(f"cannot write {SECRET_PATH}")
        ),
    )

    with pytest.raises(github_machine.GitHubMachineError) as caught:
        github_machine.connect(
            config_path=tmp_path / "home" / "config.json",
            client_id="Iv1.local",
            app_slug="yoke-local",
            device_opener=_device_opener(),
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    message = str(caught.value)
    assert SECRET_PATH not in message
    assert "could not be saved safely" in message


def test_noninteractive_onboard_sanitizes_user_token_error(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        onboard_adapter,
        "_project_needs_github_user_access_token",
        lambda parsed: True,
    )
    monkeypatch.setattr(
        onboard_adapter,
        "_github_user_access_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            github_user_tokens.GitHubUserTokenError(f"cannot read {SECRET_PATH}")
        ),
    )

    rc = onboard_adapter.onboard([
        "--non-interactive",
        "--config", str(tmp_path / "home" / "config.json"),
        "--env", "stage",
        "--api-url", "https://api.stage.upyoke.com",
        "server-token",
        "--yes",
        "--skip-identity-check",
    ])

    error = capsys.readouterr().err
    assert rc == 2
    assert SECRET_PATH not in error
    assert "yoke github connect" in error
