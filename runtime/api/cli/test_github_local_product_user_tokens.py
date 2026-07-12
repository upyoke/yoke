"""Local-product provenance coverage for GitHub user-token refresh."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest

from runtime.api.cli.test_github_app_user_tokens import NOW, _configured_credential
from yoke_cli.config import github_git_credential_store as credential_store


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
