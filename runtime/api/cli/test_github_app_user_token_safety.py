"""Crash cleanup and origin binding for local GitHub App user tokens."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest

from runtime.api.cli.test_github_app_user_tokens import NOW, _configured_credential
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_user_tokens, machine_config


def test_credential_temp_is_removed_on_keyboard_interrupt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "secrets" / f"github-app-user-{'f' * 32}.json"
    monkeypatch.setattr(
        credential_file.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        credential_file.write_json_document(
            target,
            {
                "schema_version": 2,
                "refresh_token": "refresh",
                "refresh_expires_at": "2099-01-01T00:00:00+00:00",
            },
        )

    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_machine_token_provider_rejects_mismatched_oauth_origin_before_network(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["github"]["web_url"] = "https://login.attacker.example"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[str] = []

    with pytest.raises(
        github_user_tokens.GitHubUserTokenError,
        match="canonical bases",
    ):
        github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
            now=NOW,
            opener=lambda request, timeout: calls.append(request.full_url),
        )

    assert calls == []
