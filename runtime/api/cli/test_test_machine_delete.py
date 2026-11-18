"""Deletion requires confirmation and cleans only successful local registrations."""

import pytest

from yoke_cli.commands.adapters import test_machine_delete as cli
from yoke_contracts.machine_config.capability_secret_store import (
    store_test_machine_secret,
    read_test_machine_secret,
    MachineCapabilitySecretError,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


def response(success=True):
    return FunctionCallResponse(
        success=success,
        function="test_machine.delete",
        version="v1",
        result={
            "test_machine": "lab",
            "deleted": True,
        }
        if success
        else {},
        error=None if success else FunctionError(code="held", message="held"),
    )


@pytest.mark.parametrize(
    "args",
    [[], ["--confirm"], ["--test-machine", "lab"]],
)
def test_requires_machine_name_and_confirmation(args, monkeypatch):
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
            ["--test-machine", "lab", "--confirm"]
        )
        == 0
    )
    assert calls[0]["function_id"] == "test_machine.delete"
    assert calls[0]["payload"] == {"test_machine": "lab"}
    assert calls[0]["response_recovery"] is cli._cleanup


def test_success_cleans_named_secrets_only_and_tolerates_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    for name in ("lab", "other"):
        for key in ("ssh_private_key", "desktop_password"):
            store_test_machine_secret(name, key, "private fixture")

    assert cli._cleanup(response(), None).success
    for key in ("ssh_private_key", "desktop_password"):
        assert read_test_machine_secret("lab", key) is None
        assert read_test_machine_secret("other", key) == "private fixture"
    assert cli._cleanup(response(), None).success


def test_server_refusal_keeps_credentials(monkeypatch):
    monkeypatch.setattr(
        cli,
        "delete_test_machine_secrets",
        lambda *_: pytest.fail("must not delete"),
    )
    failed = response(False)
    assert cli._cleanup(failed, None) is failed


def test_local_failure_reports_server_success_and_recovery(monkeypatch):
    def fail(*_):
        raise MachineCapabilitySecretError("directory unavailable")

    monkeypatch.setattr(cli, "delete_test_machine_secrets", fail)
    result = cli._cleanup(response(), None)
    assert not result.success
    assert result.result["deleted"] is True
    assert result.error.code == "test_machine_local_secret_cleanup_failed"
    assert "Registration deleted" in result.error.message
    assert "Recovery:" in result.error.message
