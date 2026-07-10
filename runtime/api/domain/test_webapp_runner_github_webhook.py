"""Repository-webhook reconciliation tests for the runner-fleet template."""

import os

import pytest

from runtime.api.domain.webapp_runner_fleet_test_support import (
    _REPOSITORY_TOKEN,
    _runner_stack,
)


def test_repository_automation_reconciles_with_secret_installation_token(
    monkeypatch,
):
    recorder, stack = _runner_stack(monkeypatch)

    provider = recorder.single("runnerFleetGithubProvider")
    assert provider.kwargs["owner"] == "upyoke"
    assert provider.kwargs["base_url"] == "https://api.github.com/"
    assert provider.constructor_github_token is None
    assert "token" not in provider.kwargs
    assert os.environ["GITHUB_TOKEN"] == _REPOSITORY_TOKEN

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
    ingress_ready = [
        recorder.single("runnerFleetWebhookUrlPermission"),
        recorder.single("runnerFleetWebhookUrlInvokePermission"),
    ]
    assert webhook.opts.depends_on == ingress_ready

    variable = recorder.single("runnerFleetRoutingVariable")
    assert variable.kwargs == {
        "repository": "yoke",
        "variable_name": "YOKE_LINUX_RUNS_ON",
        "value": '["self-hosted","Linux","ARM64","yoke-github-actions"]',
    }
    assert variable.opts.provider is provider
    assert variable.opts.depends_on == [webhook, *ingress_ready]
    assert _REPOSITORY_TOKEN not in repr(stack.registered_outputs)
    assert all(
        _REPOSITORY_TOKEN not in repr(getattr(resource, "kwargs", {}))
        for resource in recorder.resources
    )


def test_runner_fleet_requires_short_lived_repository_token(monkeypatch):
    with pytest.raises(
        RuntimeError,
        match=(
            "RUNNER_FLEET_GITHUB_TOKEN.*repository_hooks: write.*"
            "actions_variables: write"
        ),
    ):
        _runner_stack(monkeypatch, repository_token=None)


def test_runner_routing_defaults_to_omitted_resource(monkeypatch):
    recorder, stack = _runner_stack(monkeypatch, routing_enabled=False)

    assert not any(
        resource.resource_name == "runnerFleetRoutingVariable"
        for resource in recorder.resources
    )
    assert stack.github_actions_variable is None
    assert stack.registered_outputs["runnerFleetRoutingEnabled"] is False


def test_runner_fleet_requires_matching_ambient_provider_token(monkeypatch):
    with pytest.raises(
        RuntimeError,
        match="GITHUB_TOKEN.*match RUNNER_FLEET_GITHUB_TOKEN",
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
