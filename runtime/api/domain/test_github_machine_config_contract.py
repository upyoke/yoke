from __future__ import annotations

import pytest

from yoke_contracts.machine_config import schema as contract


@pytest.mark.parametrize("retired_field", ["scopes", "permissions"])
def test_authorization_warns_for_ignored_token_permission_fields(
    retired_field: str,
) -> None:
    payload = {
        "schema_version": 1,
        "github": {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "app_slug": "yoke",
            "client_id": "Iv1.local",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": "/local/credential.json",
                "status": "authorized",
                retired_field: [] if retired_field == "scopes" else {},
            },
        },
    }

    issues = contract.validate_payload(payload)

    assert any(
        item.code == "machine_config_key_unknown"
        and item.severity == "warning"
        and item.path == f"github.authorization.{retired_field}"
        for item in issues
    )
