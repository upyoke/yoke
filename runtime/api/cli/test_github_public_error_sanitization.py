from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _device_opener,
    _explicit_profile,
)
from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_machine
from yoke_cli.config import github_response_safety
from yoke_cli.config import github_user_tokens


SECRET_PATH = "/private/secrets/github-app-user.json"


def test_github_error_text_neutralizes_terminal_control_sequences() -> None:
    rendered = github_response_safety.safe_error_text(
        "refused\x1b]8;;https://attacker.example\x07click\x1b]8;;\x07\x9b31m",
    )

    assert "refused" in rendered
    assert "click" in rendered
    assert all(ord(char) >= 32 and ord(char) != 127 for char in rendered)


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


@pytest.mark.parametrize("invalid_body", [
    b"credential-body-must-not-leak-\xff",
    b"credential-body-must-not-leak" + b"x" * (
        github_git_credential_file.MAX_CREDENTIAL_DOCUMENT_BYTES + 1
    ),
])
def test_git_credential_helper_hides_invalid_credential_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_body: bytes,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    credential = secret_dir / f"github-app-user-{'a' * 32}.json"
    credential.write_bytes(invalid_body)
    credential.chmod(0o600)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "github": {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "client_id": "Iv1.safe",
            "authorization": {
                "kind": "github_app_user_authorization",
                "status": "authorized",
                "refresh_credential_ref": str(credential),
            },
        },
    }), encoding="utf-8")

    rc = github_git_credential_helper.main(
        ["--config", str(config), "get"],
        stdin=StringIO("protocol=https\nhost=github.com\n\n"),
        stdout=StringIO(),
    )

    error = capsys.readouterr().err
    assert rc == 1
    assert "credential-body-must-not-leak" not in error
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
            **_explicit_profile(),
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
        "--api-url", "https://yoke.example.test",
        "server-token",
        "--yes",
        "--skip-identity-check",
    ])

    error = capsys.readouterr().err
    assert rc == 2
    assert SECRET_PATH not in error
    assert "yoke github connect" in error
