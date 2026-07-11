"""Repository and authority binding for hosted runner-fleet tokens."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import json_helper, runner_fleet_token_broker as broker


def _arrange(monkeypatch, *, digest="a" * 64):
    settings = SimpleNamespace(project="yoke")
    values = {
        "runner_fleet_repo": "upyoke/yoke",
        "runner_fleet_github_installation_id": "1234",
    }
    envelope = json_helper.dumps_compact({
        "schema": 1,
        "authority": {"repo": "upyoke/yoke"},
        "sha256": digest,
    })
    monkeypatch.setattr(
        broker, "build_pulumi_stack_config", lambda conn, project: {"ok": True}
    )
    monkeypatch.setattr(
        broker, "settings_from_stack_config", lambda payload: settings
    )
    monkeypatch.setattr(
        broker,
        "authority_intent_from_settings",
        lambda selected: (envelope, values, "aws-admin", "us-east-1"),
    )


def test_broker_requests_only_runner_repository_permissions(monkeypatch):
    _arrange(monkeypatch)
    calls = []

    def resolve(project, *, conn, required_permissions):
        calls.append((project, conn, required_permissions))
        return SimpleNamespace(
            token="ghs_scoped",
            token_expires_at="2026-07-10T12:30:00+00:00",
            token_source="github_app_installation",
            repo="upyoke/yoke",
            installation_id="1234",
        )

    grant = broker.issue_runner_fleet_token(
        object(),
        project="yoke",
        authority_sha256="a" * 64,
        auth_resolver=resolve,
    )

    assert grant.token == "ghs_scoped"
    assert calls[0][2] == {
        "actions_variables": "read",
        "repository_hooks": "read",
    }
    assert "administration" not in calls[0][2]


def test_broker_rejects_stale_snapshot_before_mint(monkeypatch):
    _arrange(monkeypatch, digest="b" * 64)

    with pytest.raises(broker.RunnerFleetAuthorityMismatch):
        broker.issue_runner_fleet_token(
            object(),
            project="yoke",
            authority_sha256="a" * 64,
            auth_resolver=lambda *args, **kwargs: pytest.fail("minted token"),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"token_source": "github_app_user"}, "does not match"),
        ({"repo": "upyoke/platform"}, "does not match"),
        ({"installation_id": "9999"}, "does not match"),
        ({"token_expires_at": ""}, "expiry metadata"),
    ],
)
def test_broker_rejects_noncanonical_authority(monkeypatch, overrides, message):
    _arrange(monkeypatch)
    auth = {
        "token": "ghs_scoped",
        "token_expires_at": "2026-07-10T12:30:00+00:00",
        "token_source": "github_app_installation",
        "repo": "upyoke/yoke",
        "installation_id": "1234",
    }
    auth.update(overrides)

    with pytest.raises(broker.RunnerFleetTokenBrokerError, match=message):
        broker.issue_runner_fleet_token(
            object(),
            project="yoke",
            authority_sha256="a" * 64,
            auth_resolver=lambda *args, **kwargs: SimpleNamespace(**auth),
        )
