"""Local-product provenance coverage for GitHub user-token refresh."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest

from runtime.api.cli.test_github_app_user_tokens import NOW, _configured_credential
from runtime.api.cli.test_github_app_user_tokens import _FakeResponse
from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_git_credential_store as credential_store
from yoke_cli.config import machine_config


def test_helper_refresh_proves_local_product_profile_against_bundle(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    github = config["github"]
    github["profile_source"] = "local_product"
    bundled = {
        field: github[field]
        for field in ("client_id", "app_slug", "app_id", "api_url", "web_url")
    }
    monkeypatch.setattr(
        credential_store.token_contract,
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
        credential_store.token_contract.LocalProductGitHubAppProfile(**bundled),
    )

    credential_store.github_service_profile_proof.prove_local_product(github)
    github["client_id"] = "Iv1.drifted"
    with pytest.raises(
        credential_store.GitHubCredentialStoreError,
        match="saved local product GitHub App identity differs",
    ):
        credential_store.access_token_from_config(
            config,
            config_path=config_path,
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("profile mismatch must precede OAuth")
            ),
        )


def test_explicit_local_refresh_ignores_active_hosted_connection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config_path, _credential_path = _configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1),
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["active_env"] = "prod"
    config["connections"] = {
        "prod": {
            "transport": "https",
            "api_url": "https://api.upyoke.com",
            "credential_source": {
                "kind": "token_file",
                "path": str(tmp_path / "secrets" / "prod.token"),
            },
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    token = github_local_user_access.access_token(
        config_path=config_path,
        local_connection_selected=True,
        now=NOW,
        opener=lambda request, timeout: _FakeResponse({
            "access_token": "local-access",
            "expires_in": 28_800,
            "refresh_token": "local-refresh",
            "refresh_token_expires_in": 15_552_000,
        }),
    )

    assert token.access_token == "local-access"
