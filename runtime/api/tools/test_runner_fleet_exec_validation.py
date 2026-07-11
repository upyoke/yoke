"""Validation and refusal coverage for runner-fleet child authority."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.tools import runner_fleet_exec
from runtime.api.tools.runner_fleet_exec_test_support import (
    _PRIVATE_KEY,
    _Process,
    _TOKEN,
    _runner_values,
    _write_snapshot,
)


@pytest.fixture(autouse=True)
def _isolate_runner_authority_from_ci(monkeypatch):
    """Local-authority cases must not inherit the test host's CI marker."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def test_project_mismatch_refuses_before_runner_validation(
    tmp_path,
    monkeypatch,
):
    snapshot = _write_snapshot(tmp_path / "stack-config.json")
    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        lambda *args, **kwargs: pytest.fail("validated runner values"),
    )

    with pytest.raises(
        runner_fleet_exec.RunnerFleetExecError,
        match="does not match requested project",
    ):
        runner_fleet_exec.execute_runner_fleet_command(
            "yoke",
            snapshot,
            ["pulumi", "up"],
        )


def test_repository_token_can_create_or_delete_routing_variable():
    expected = {
        "actions_variables": "write",
        "repository_hooks": "write",
    }
    for routing_enabled in (False, True):
        assert (
            runner_fleet_exec._repository_automation_permissions(
                _runner_values(routing_enabled=routing_enabled)
            )
            == expected
        )


def test_repository_provider_token_never_includes_administration():
    for routing_enabled in (False, True):
        permissions = runner_fleet_exec._repository_automation_permissions(
            _runner_values(routing_enabled=routing_enabled)
        )
        assert "administration" not in permissions


def test_envelope_project_must_match_renderer_snapshot(tmp_path):
    snapshot = _write_snapshot(
        tmp_path / "stack-config.json",
        project="buzz",
        envelope_project="yoke",
    )

    with pytest.raises(
        runner_fleet_exec.RunnerFleetExecError,
        match="envelope project does not match",
    ):
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["pulumi", "up"],
        )


def test_unknown_snapshot_schema_refuses(tmp_path):
    snapshot = _write_snapshot(
        tmp_path / "stack-config.json",
        schema=99,
    )

    with pytest.raises(
        runner_fleet_exec.RunnerFleetExecError,
        match="schema 99.*not supported",
    ):
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["pulumi", "up"],
        )


def test_runner_validation_is_enabled_and_fails_before_aws(
    tmp_path,
    monkeypatch,
):
    snapshot = _write_snapshot(tmp_path / "stack-config.json")
    validation_calls: list[tuple[str, bool]] = []

    def invalid_values(settings, *, fallback_repo, enabled):
        validation_calls.append((fallback_repo, enabled))
        raise ValueError("runner-fleet binding is invalid")

    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        invalid_values,
    )

    with pytest.raises(
        runner_fleet_exec.RunnerFleetExecError,
        match="runner-fleet binding is invalid",
    ):
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["pulumi", "up"],
            aws_env_loader=lambda *args, **kwargs: pytest.fail("loaded AWS env"),
        )
    assert validation_calls == [("", True)]


def test_aws_region_must_come_from_snapshot(tmp_path, monkeypatch):
    snapshot = _write_snapshot(
        tmp_path / "stack-config.json",
        region=None,
    )
    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        lambda *args, **kwargs: _runner_values(),
    )

    with pytest.raises(
        runner_fleet_exec.RunnerFleetExecError,
        match="selected AWS capability 'aws-admin'.*declares no region",
    ):
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["pulumi", "up"],
            aws_env_loader=lambda *args, **kwargs: pytest.fail("loaded AWS env"),
        )


@pytest.mark.parametrize("phase", ["secret", "token"])
def test_sensitive_phase_failures_are_redacted(
    tmp_path,
    monkeypatch,
    phase,
):
    snapshot = _write_snapshot(tmp_path / "stack-config.json")
    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        lambda *args, **kwargs: _runner_values(),
    )

    def secret_loader(*args, **kwargs):
        if phase == "secret":
            raise RuntimeError(f"secret failure {_PRIVATE_KEY}")
        return _PRIVATE_KEY

    def token_minter(**kwargs):
        raise RuntimeError(f"token failure {_PRIVATE_KEY} {_TOKEN}")

    with pytest.raises(runner_fleet_exec.RunnerFleetExecError) as raised:
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["pulumi", "up"],
            aws_env_loader=lambda project, region, **kwargs: {"AWS_REGION": region},
            secret_loader=secret_loader,
            token_minter=token_minter,
        )

    message = str(raised.value)
    assert _PRIVATE_KEY.strip() not in message
    assert _TOKEN not in message
    if phase == "secret":
        assert "could not be loaded" in message
    else:
        assert "could not be minted" in message


def test_missing_child_executable_propagates_for_cli_mapping(
    tmp_path,
    monkeypatch,
):
    snapshot = _write_snapshot(tmp_path / "stack-config.json")
    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        lambda *args, **kwargs: _runner_values(),
    )

    with pytest.raises(FileNotFoundError):
        runner_fleet_exec.execute_runner_fleet_command(
            "buzz",
            snapshot,
            ["missing-pulumi"],
            aws_env_loader=lambda project, region, **kwargs: {"AWS_REGION": region},
            secret_loader=lambda *args, **kwargs: _PRIVATE_KEY,
            token_minter=lambda **kwargs: SimpleNamespace(token=_TOKEN),
            child_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
                FileNotFoundError
            ),
        )


def test_custom_runner_aws_capability_selects_region_and_credentials(
    tmp_path,
    monkeypatch,
):
    snapshot = _write_snapshot(
        tmp_path / "stack-config.json",
        region="eu-west-1",
        aws_capability="runner-aws",
    )
    monkeypatch.setattr(
        runner_fleet_exec,
        "runner_fleet_values",
        lambda *args, **kwargs: _runner_values(),
    )
    env_calls = []

    def aws_env_loader(project, region, *, capability_type):
        env_calls.append((project, region, capability_type))
        return {"AWS_REGION": region}

    rc = runner_fleet_exec.execute_runner_fleet_command(
        "buzz",
        snapshot,
        ["pulumi", "preview"],
        aws_env_loader=aws_env_loader,
        secret_loader=lambda *args, **kwargs: _PRIVATE_KEY,
        token_minter=lambda **kwargs: SimpleNamespace(token=_TOKEN),
        child_factory=lambda *args, **kwargs: _Process(),
    )

    assert rc == 0
    assert env_calls == [("buzz", "eu-west-1", "runner-aws")]
