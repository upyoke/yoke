"""host-command's native Windows flags: --fixture, --elevated, --second-user."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import agent_mission_host_command_cli as cli
from yoke_core.domain import agent_mission_host_fixture as fixture

BASE = ["--execution-id", "e1", "--requirement-id", "7", "--item", "YOK-1"]


@pytest.mark.parametrize("flag", ["--fixture", "--elevated", "--second-user"])
@pytest.mark.parametrize("os_name", ["macos", "linux", "wsl"])
def test_windows_flags_refuse_on_other_oses(flag, os_name):
    with pytest.raises(HostControlLocalError) as error:
        fixture.require_native_windows({"os": os_name}, flag)
    assert error.value.code == fixture.WINDOWS_ONLY
    assert flag in error.value.recovery_hint


class _Control:
    def __init__(self):
        self.variants = []

    def variant(self, **kwargs):
        self.variants.append(kwargs)
        return ("variant", kwargs)


def _execution(os_name="windows"):
    return SimpleNamespace(control=_Control(), material=SimpleNamespace(settings={"os": os_name}))


def test_plain_commands_keep_the_lease_control():
    execution = _execution("macos")
    assert fixture.windows_host_variant(execution, elevated=False, second_user=False) is execution.control


def test_windows_variants_select_the_elevated_or_second_user_control():
    execution = _execution()
    assert fixture.windows_host_variant(execution, elevated=True, second_user=False)[1] == {"elevated": True, "second_user": False}
    assert fixture.windows_host_variant(execution, elevated=False, second_user=True)[1] == {"elevated": False, "second_user": True}
    with pytest.raises(HostControlLocalError) as error:
        fixture.windows_host_variant(execution, elevated=True, second_user=True)
    assert error.value.code == "native_windows_flags_conflict"
    with pytest.raises(HostControlLocalError):
        fixture.windows_host_variant(_execution("linux"), elevated=True, second_user=False)


def test_core_control_variant_passes_the_second_user_as_login_user(monkeypatch):
    from yoke_core.domain import ssh_native_windows_host_control as control_module

    built = []

    class Probe(control_module.SshNativeWindowsHostControl):
        def __init__(self, material, *, elevated=False, login_user=None):
            built.append((elevated, login_user))
            self.material = material

    original = Probe(SimpleNamespace())
    original.variant(second_user=True)
    original.variant(elevated=True)
    assert built[1:] == [(False, "Zoë Tester"), (True, None)]


def test_undo_requires_fixture(capsys):
    with pytest.raises(SystemExit):
        cli.run([*BASE, "--undo", "--", "whoami"])
    assert "--undo applies only with --fixture" in capsys.readouterr().err


def test_fixture_takes_no_command(capsys):
    with pytest.raises(SystemExit):
        cli.run([*BASE, "--fixture", "applocker", "--", "whoami"])
    assert "--fixture takes no command" in capsys.readouterr().err


def test_fixture_runs_through_the_lease_and_prints_its_records(monkeypatch, capsys):
    contract = {"settings": {"os": "windows"}}
    calls = []
    monkeypatch.setattr(cli, "resolve_mission_contract", lambda parsed, prog: contract)
    monkeypatch.setattr(
        fixture,
        "execute_agent_mission_host_fixture",
        lambda raw, *, name, undo: calls.append((raw, name, undo)) or {"exit_code": 0, "fixture": name, "verify_records": [{"ok": True}]},
    )
    monkeypatch.setattr("yoke_core.domain.machine_qa_host_control.register_test_machine_host_control", lambda: None)
    assert cli.run([*BASE, "--fixture", "applocker", "--undo"]) == 0
    assert calls == [(contract, "applocker", True)]
    printed = json.loads(capsys.readouterr().out)
    assert printed["fixture"] == "applocker" and printed["verify_records"] == [{"ok": True}]


def test_elevated_refuses_on_another_os_before_the_host_is_touched(monkeypatch, capsys):
    monkeypatch.setattr(cli, "resolve_mission_contract", lambda parsed, prog: {"settings": {"os": "macos"}})
    executed = []
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_agent_mission_host_command",
        lambda *a, **kw: executed.append(a),
    )
    assert cli.run([*BASE, "--elevated", "--", "whoami"]) == 2
    assert fixture.WINDOWS_ONLY in capsys.readouterr().err
    assert executed == []
