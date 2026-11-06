"""Deletion requires confirmation and cleans only successful local registrations."""

import pytest

from yoke_cli.commands.adapters import test_machine_delete as cli
from yoke_cli.config.capability_secrets import (
    store_machine_capability_secret,
    read_machine_capability_secret,
    MachineCapabilitySecretError,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


def response(success=True):
    return FunctionCallResponse(
        success=success,
        function="test_machine.delete",
        version="v1",
        result={
            "project": "example",
            "capability_type": "test-machine:lab",
            "deleted": True,
        }
        if success
        else {},
        error=None if success else FunctionError(code="held", message="held"),
    )


@pytest.mark.parametrize(
    "args",
    [[], ["--project", "example"], ["--project", "example", "--test-machine", "lab"]],
)
def test_requires_explicit_project_name_and_confirmation(args, monkeypatch):
    monkeypatch.setattr(
        cli, "dispatch_and_emit", lambda **_: pytest.fail("must not dispatch")
    )
    try:
        assert cli.test_machine_delete(args) == 2
    except SystemExit as exc:
        assert exc.code == 2


def test_dispatches_delete_and_registers_cleanup(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    assert (
        cli.test_machine_delete(
            ["--project", "example", "--test-machine", "lab", "--confirm"]
        )
        == 0
    )
    assert calls[0]["function_id"] == "test_machine.delete"
    assert calls[0]["payload"] == {"project": "example", "test_machine": "lab"}
    assert calls[0]["response_recovery"] is cli._cleanup


def test_success_cleans_named_secrets_only_and_tolerates_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    for project, cap, key in [
        ("example", "test-machine:lab", "desktop_password"),
        ("example", "test-machine", "ssh_private_key"),
        ("other", "test-machine:lab", "desktop_password"),
        ("example", "test-machine:other", "desktop_password"),
    ]:
        store_machine_capability_secret(project, cap, key, "private fixture")
    assert cli._cleanup(response(), None).success
    assert (
        read_machine_capability_secret(
            "example", "test-machine:lab", "desktop_password"
        )
        is None
    )
    for project, cap, key in [
        ("example", "test-machine", "ssh_private_key"),
        ("other", "test-machine:lab", "desktop_password"),
        ("example", "test-machine:other", "desktop_password"),
    ]:
        assert read_machine_capability_secret(project, cap, key) == "private fixture"
    assert cli._cleanup(response(), None).success


def test_server_refusal_keeps_credentials(monkeypatch):
    monkeypatch.setattr(
        cli,
        "delete_machine_capability_secrets",
        lambda *_: pytest.fail("must not delete"),
    )
    failed = response(False)
    assert cli._cleanup(failed, None) is failed


def test_local_failure_reports_server_success_and_recovery(monkeypatch):
    def fail(*_):
        raise MachineCapabilitySecretError("directory unavailable")

    monkeypatch.setattr(cli, "delete_machine_capability_secrets", fail)
    result = cli._cleanup(response(), None)
    assert not result.success
    assert result.result["deleted"] is True
    assert result.error.code == "test_machine_local_secret_cleanup_failed"
    assert "Registration deleted" in result.error.message
    assert "Recovery:" in result.error.message
