"""Contracts for the warm-host ephemeral runner execution loop."""

from __future__ import annotations

import subprocess
import types

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
)


def _cycle(monkeypatch, **overrides):
    args = types.SimpleNamespace(
        deploy_namespace="yoke",
        github_repo="upyoke/yoke",
        github_web_url="https://github.com",
        runner_labels=[
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ],
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    module = _load_template_module(
        monkeypatch, _Recorder(), "webapp_runner_host_cycle.py",
    )
    return module._runner_cycle_script(
        args=args,
        region="us-east-1",
        github_broker_function="runnerFleetGithubBroker.name",
    )


def test_cycle_rearms_a_fresh_ephemeral_runner_after_each_job(monkeypatch):
    cycle = _cycle(monkeypatch)

    subprocess.run(
        ["bash", "-n"], input=cycle, text=True, check=True,
        capture_output=True,
    )
    assert "github_broker register" in cycle
    assert "github_broker ready" in cycle
    assert "github_broker failed" in cycle
    assert "--ephemeral" in cycle
    assert "./run.sh" in cycle
    assert "cycle.XXXXXX" in cycle
    assert "while true" in cycle
    assert ".registration_token // empty" in cycle


def test_cycle_treats_rendered_values_as_data(monkeypatch):
    cycle = _cycle(
        monkeypatch,
        deploy_namespace="yoke$(exit 77)",
        github_repo="acme/repo$(exit 78)",
        github_web_url="https://github.example.test$(exit 79)",
        runner_labels=["self-hosted", "label$(exit 80)"],
    )

    subprocess.run(
        ["bash", "-n"], input=cycle, text=True, check=True,
        capture_output=True,
    )
    assignments = cycle.split("\nSTATE_DIR=", 1)[0]
    result = subprocess.run(
        ["bash"],
        input=assignments + '\nprintf "%s" "$GITHUB_REPO"',
        text=True,
        check=True,
        capture_output=True,
    )
    assert result.stdout == "acme/repo$(exit 78)"
