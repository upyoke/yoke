"""GitHub App identity issuer validation without key handling."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_app_identity import (
    GitHubAppIdentityVerificationError,
    validate_identity_payload,
)


@pytest.mark.parametrize("issuer", ["123456", "Iv1.client"])
def test_identity_accepts_app_id_or_client_id(issuer):
    identity = validate_identity_payload(
        issuer,
        {"id": 123456, "client_id": "Iv1.client", "slug": "yoke"},
    )

    assert identity.app_id == 123456
    assert identity.slug == "yoke"


def test_identity_rejects_another_issuer():
    with pytest.raises(GitHubAppIdentityVerificationError, match="does not match"):
        validate_identity_payload(
            "123456",
            {"id": 999, "client_id": "Iv1.other", "slug": "other"},
        )
