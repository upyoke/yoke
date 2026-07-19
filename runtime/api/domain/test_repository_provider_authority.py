"""Repository provider authority stays broker-bound and repo-scoped."""

from __future__ import annotations

import hashlib

import pytest

from runtime.api.tools.runner_fleet_exec_test_support import _runner_values
from yoke_core.domain import json_helper, repository_provider_authority
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


def _settings() -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="platform",
        deploy_namespace="yoke",
        display_name="Platform",
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=(),
        capabilities={},
    )


def test_provider_intent_is_digest_bound_to_the_requested_repository(
    monkeypatch,
):
    monkeypatch.setattr(
        repository_provider_authority,
        "runner_fleet_values",
        lambda *args, **kwargs: {
            **_runner_values(),
            "runner_fleet_repo": "upyoke/platform",
            "runner_fleet_github_repo_name": "platform",
        },
    )

    envelope = json_helper.loads_text(
        repository_provider_authority.repository_provider_intent_from_settings(
            _settings(), expected_repo="upyoke/platform"
        )
    )

    authority = envelope["authority"]
    canonical = json_helper.dumps_compact(dict(sorted(authority.items())))
    assert envelope["schema"] == 1
    assert authority["repo"] == "upyoke/platform"
    assert authority["token_broker_function"].endswith(
        "runner-fleet-token-broker"
    )
    assert envelope["sha256"] == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_provider_intent_refuses_a_different_repository(monkeypatch):
    monkeypatch.setattr(
        repository_provider_authority,
        "runner_fleet_values",
        lambda *args, **kwargs: _runner_values(),
    )

    with pytest.raises(ValueError, match="does not match"):
        repository_provider_authority.repository_provider_intent_from_settings(
            _settings(), expected_repo="upyoke/platform"
        )
