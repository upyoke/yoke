"""Repository-webhook reconciliation tests for the runner-fleet template."""

import os

import pytest

from runtime.api.domain.test_webapp_runner_fleet_stack import (
    _WEBHOOK_TOKEN,
    _runner_stack,
)


def test_repository_webhook_reconciles_with_secret_installation_token(
    monkeypatch,
):
    recorder, stack = _runner_stack(monkeypatch)

    provider = recorder.single("runnerFleetGithubProvider")
    assert provider.kwargs["owner"] == "upyoke"
    assert provider.kwargs["base_url"] == "https://api.github.com/"
    assert provider.constructor_github_token is None
    assert "token" not in provider.kwargs
    assert os.environ["GITHUB_TOKEN"] == _WEBHOOK_TOKEN

    webhook = recorder.single("runnerFleetGithubWebhook")
    assert webhook.kwargs["repository"] == "yoke"
    assert webhook.kwargs["events"] == ["workflow_job"]
    assert webhook.kwargs["active"] is True
    configuration = webhook.kwargs["configuration"]
    assert configuration["url"].value == "runnerFleetWebhookUrl.function_url"
    assert configuration["content_type"] == "json"
    assert configuration["insecure_ssl"] is False
    assert configuration["secret"].value == (
        "runnerFleetWebhookSecretValue.result"
    )
    assert webhook.opts.provider is provider
    assert _WEBHOOK_TOKEN not in repr(stack.registered_outputs)
    assert all(
        _WEBHOOK_TOKEN not in repr(getattr(resource, "kwargs", {}))
        for resource in recorder.resources
    )


def test_runner_fleet_requires_short_lived_webhook_token(monkeypatch):
    with pytest.raises(
        RuntimeError,
        match="RUNNER_FLEET_WEBHOOK_TOKEN.*repository_hooks: write",
    ):
        _runner_stack(monkeypatch, webhook_token=None)


def test_runner_fleet_requires_matching_ambient_provider_token(monkeypatch):
    with pytest.raises(
        RuntimeError,
        match="GITHUB_TOKEN.*match RUNNER_FLEET_WEBHOOK_TOKEN",
    ):
        _runner_stack(monkeypatch, github_provider_token="different-token")


def test_repository_webhook_provider_uses_selected_api_origin(monkeypatch):
    api_url = "https://github.acme.test/api/v3"
    recorder, _stack = _runner_stack(
        monkeypatch,
        github_api_url=api_url,
        github_web_url="https://github.acme.test",
    )

    provider = recorder.single("runnerFleetGithubProvider")
    assert provider.kwargs["base_url"] == api_url + "/"
