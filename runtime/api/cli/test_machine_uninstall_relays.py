"""The uninstall bridge preserves the native cleanup refusal."""

from subprocess import CompletedProcess

import pytest

from yoke_cli.config import machine_uninstall_relays as relays
from yoke_cli.config.machine_uninstall_inventory import UninstallError


def test_saved_service_cleanup_names_home_not_active_alias(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        relays.subprocess,
        "run",
        lambda args, **kwargs: (
            calls.append((args, kwargs)) or CompletedProcess(args, 0, "removed", "")
        ),
    )
    relays.remove_saved_services(tmp_path)
    args, kwargs = calls[0]
    assert args[-3:] == ["uninstall-owned", "--machine-home", str(tmp_path)]
    assert "--environment" not in args and "--env" not in args
    assert kwargs["check"] is False and kwargs["timeout"] == 300


def test_native_failure_names_recovery_and_redacts_token(monkeypatch, tmp_path):
    monkeypatch.setattr(
        relays.subprocess,
        "run",
        lambda args, **kwargs: CompletedProcess(
            args,
            1,
            "",
            "uninstall_relay_not_stopped: retry yoke_v1_" + "a" * 43,
        ),
    )
    with pytest.raises(UninstallError, match="uninstall_relay_not_stopped") as error:
        relays.remove_saved_services(tmp_path)
    assert "a" * 43 not in str(error.value)
    assert "machine home and CLI remain" in str(error.value)
