"""Relay credential-presence observation excludes secret material."""

from pathlib import Path

import pytest

from yoke_harness.session_relay_credentials import observe_credential_presence


def test_presence_is_boolean_only(tmp_path: Path):
    aws = tmp_path / "capability-secrets" / "project" / "aws-admin"
    aws.mkdir(parents=True)
    (aws / "access_key_id").write_text("secret", encoding="utf-8")
    (aws / "secret_access_key").write_text("more-secret", encoding="utf-8")
    config = {
        "github": {
            "authorization": {
                "status": "authorized",
                "refresh_credential_ref": "private-ref",
            }
        }
    }
    result = observe_credential_presence(
        config,
        versions={"codex-cli": "1.0"},
        plan_limits={"codex-cli": {"windows": [{"status": "ok"}]}},
        secret_root=tmp_path,
    )

    assert result == {
        "github": True,
        "aws": True,
        "harnesses": {
            "claude-cli": False,
            "codex-cli": True,
            "cursor-cli": False,
        },
    }
    assert "secret" not in repr(result)


@pytest.mark.parametrize(
    "reason", ["stale_credential", "quota_http_403", "quota_http_429"]
)
def test_harness_presence_is_not_claimed_without_a_successful_safe_probe(
    tmp_path: Path,
    reason: str,
):
    result = observe_credential_presence(
        {},
        versions={"codex-cli": "1.0"},
        plan_limits={
            "codex-cli": {"windows": [{"status": "unknown", "reason": reason}]}
        },
        secret_root=tmp_path,
    )

    assert result["harnesses"]["codex-cli"] is False
