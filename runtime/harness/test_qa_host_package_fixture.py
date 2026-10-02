"""Package fixtures undo complete mission deltas, including transitive installs."""

import contextlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import (
    MACHINE_QA_DIAGNOSTIC_LIMIT,
    HostControlLocalError,
)
from yoke_harness.qa_host_package_fixture import (
    _PACKAGE_SCRIPT,
    restore_host_packages,
)


def _execute(
    monkeypatch, journal, inventory, mode, declaration=None, *, apt_failure=False
):
    def command(argv, **kwargs):
        if argv[0] == "dpkg-query":
            output = "".join(
                f"{name}\t{version}\tinstalled\n" for name, version in inventory.items()
            )
            return subprocess.CompletedProcess(argv, 0, output, "")
        assert argv[:7] == [
            "sudo",
            "-n",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "-y",
            argv[6],
        ]
        operation = argv[6]
        if apt_failure:
            return subprocess.CompletedProcess(argv, 100, "", "Version unavailable")
        for value in argv[argv.index("--") + 1 :]:
            name, _, version = value.partition("=")
            if operation == "purge":
                inventory.pop(name, None)
            else:
                inventory[name] = version or "1.0"
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", command)
    monkeypatch.setattr(
        sys, "argv", ["fixture", mode, str(journal), json.dumps(declaration or {})]
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(_PACKAGE_SCRIPT, "<host-package-fixture>", "exec"), {})
    return json.loads(output.getvalue())


def test_stock_fixture_removes_previous_direct_and_transitive_installs(
    monkeypatch, tmp_path
):
    journal = tmp_path / "golden.qa-packages.json"
    inventory = {"python3-minimal": "3.12", "tmux": "3.4"}
    declaration = {"os_packages": {"absent": ["python3.12-venv"], "present": []}}
    initial = _execute(monkeypatch, journal, inventory, "restore", declaration)
    assert initial["ok"] and initial["changes"]["installed"] == {}
    inventory.update({"python3.12-venv": "3.12", "python3-pip-whl": "24.0"})
    changed = _execute(monkeypatch, journal, inventory, "record")
    assert set(changed["changes"]["installed"]) == {
        "python3.12-venv",
        "python3-pip-whl",
    }
    restored = _execute(monkeypatch, journal, inventory, "restore", declaration)
    assert inventory == {"python3-minimal": "3.12", "tmux": "3.4"}
    assert set(restored["restored_previous_changes"]["installed"]) == {
        "python3.12-venv",
        "python3-pip-whl",
    }
    assert journal.stat().st_mode & 0o777 == 0o600


def test_declared_present_package_does_not_leak_to_next_mission(monkeypatch, tmp_path):
    journal = tmp_path / "golden.qa-packages.json"
    inventory = {"tmux": "3.4"}
    _execute(
        monkeypatch,
        journal,
        inventory,
        "restore",
        {"os_packages": {"present": ["python3.12-venv"]}},
    )
    assert "python3.12-venv" in inventory
    inventory["tmux"] = "3.5"
    _execute(
        monkeypatch,
        journal,
        inventory,
        "restore",
        {"os_packages": {"absent": ["python3.12-venv"]}},
    )
    assert inventory == {"tmux": "3.5"}
    assert json.loads(journal.read_text())["base_packages"] == {"tmux": "3.5"}


def test_ambient_security_upgrade_is_rebased_without_package_mutation(
    monkeypatch, tmp_path
):
    journal = tmp_path / "golden.qa-packages.json"
    inventory = {"libxpm4:arm64": "1:3.5.17-1ubuntu0.24.04.1"}
    _execute(monkeypatch, journal, inventory, "restore")
    inventory["libxpm4:arm64"] = "1:3.5.17-1ubuntu0.24.04.2"
    restored = _execute(monkeypatch, journal, inventory, "restore", apt_failure=True)
    assert restored["restored_previous_changes"] == {
        "installed": {},
        "removed": {},
        "changed": {},
    }
    assert json.loads(journal.read_text())["base_packages"] == inventory


def test_fixture_removed_and_changed_packages_are_reinstated(monkeypatch, tmp_path):
    journal = tmp_path / "golden.qa-packages.json"
    inventory = {"removed": "1", "changed": "1", "ambient": "1"}
    _execute(monkeypatch, journal, inventory, "restore")
    inventory.pop("removed")
    inventory["changed"] = "2"
    _execute(monkeypatch, journal, inventory, "record")
    inventory["ambient"] = "2"
    restored = _execute(monkeypatch, journal, inventory, "restore")
    assert inventory == {"removed": "1", "changed": "1", "ambient": "2"}
    assert restored["restored_previous_changes"]["removed"] == {"removed": "1"}
    assert restored["restored_previous_changes"]["changed"] == {"changed": "1"}
    assert json.loads(journal.read_text())["base_packages"] == inventory


def test_unrestorable_owned_change_preserves_journal_and_refuses(monkeypatch, tmp_path):
    journal = tmp_path / "golden.qa-packages.json"
    inventory = {"changed": "1"}
    _execute(monkeypatch, journal, inventory, "restore")
    inventory["changed"] = "2"
    _execute(monkeypatch, journal, inventory, "record")
    before = journal.read_text()
    with pytest.raises(SystemExit) as refused:
        _execute(monkeypatch, journal, inventory, "restore", apt_failure=True)
    assert refused.value.code == 100
    assert journal.read_text() == before
    assert inventory == {"changed": "2"}


def test_missing_attribution_refuses_before_mutation(monkeypatch, tmp_path):
    journal = tmp_path / "golden.qa-packages.json"
    journal.write_text(json.dumps({"base_packages": {"changed": "1"}}))
    inventory = {"changed": "2"}
    with pytest.raises(RuntimeError, match="os_package_attribution_unproved"):
        _execute(monkeypatch, journal, inventory, "restore", apt_failure=True)
    assert inventory == {"changed": "2"}


@pytest.mark.parametrize(
    "declaration", [None, {"os_packages": None}, {"os_packages": {"present": "tmux"}}]
)
def test_malformed_attribution_refuses_before_mutation(
    monkeypatch, tmp_path, declaration
):
    journal = tmp_path / "golden.qa-packages.json"
    journal.write_text(
        json.dumps(
            {
                "base_packages": {},
                "declared": declaration,
                "changes": {"installed": {}, "removed": {}, "changed": {}},
            }
        )
    )
    with pytest.raises(RuntimeError, match="os_package_attribution_unproved"):
        _execute(monkeypatch, journal, {}, "restore", apt_failure=True)


def test_declared_package_is_restored_after_interrupted_fixture(monkeypatch, tmp_path):
    journal = tmp_path / "golden.qa-packages.json"
    journal.write_text(
        json.dumps(
            {
                "base_packages": {"tmux": "1"},
                "declared": {"os_packages": {"absent": ["tmux"]}},
                "changes": {"installed": {}, "removed": {}, "changed": {}},
            }
        )
    )
    inventory = {"ambient": "2"}
    _execute(monkeypatch, journal, inventory, "restore")
    assert inventory == {"tmux": "1", "ambient": "2"}


@pytest.mark.parametrize("host_os", ["linux", "windows"])
def test_supported_hosts_share_restore_attribution_script(host_os):
    commands = []

    def run_command(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    control = SimpleNamespace(
        os=host_os, golden_baseline_path="/tmp/golden", run_command=run_command
    )
    assert restore_host_packages(control, {"os_packages": {}})["ok"]
    assert commands[0][2] == _PACKAGE_SCRIPT
    assert commands[0][3] == "restore"


def test_declaration_on_unsupported_host_refuses_before_any_command():
    control = SimpleNamespace(os="macos")
    with pytest.raises(ValueError, match="os_package_fixture_unsupported"):
        restore_host_packages(control, {"os_packages": {"absent": ["python3-venv"]}})


@pytest.mark.parametrize(
    "operation,packages", [("purge", ["tmux"]), ("install", ["xdotool"])]
)
def test_remote_apt_failure_keeps_operation_and_safe_output(
    monkeypatch, tmp_path, operation, packages
):
    stdout = "download private-token " + "x" * 900
    stderr = "E: held packages private-token " + "y" * 900
    calls = []

    def command(argv, **kwargs):
        if argv[0] == "dpkg-query":
            return subprocess.CompletedProcess(argv, 0, "tmux\t3.4\tinstalled\n", "")
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 100, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", command)
    declaration = {
        "os_packages": {"absent" if operation == "purge" else "present": packages}
    }
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fixture",
            "restore",
            str(tmp_path / "golden.qa-packages.json"),
            json.dumps(declaration),
        ],
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
        exec(compile(_PACKAGE_SCRIPT, "<host-package-fixture>", "exec"), {})
    assert stopped.value.code == 100
    assert len(calls) == 1
    assert calls[0][6] == operation
    assert calls[0][calls[0].index("--") + 1 :] == packages
    remote = json.loads(output.getvalue())["apt_failure"]
    assert remote == {
        "operation": operation,
        "packages": packages,
        "exit_code": 100,
        "stdout": stdout,
        "stderr": stderr,
    }
    control = SimpleNamespace(
        os="linux",
        golden_baseline_path="/var/lib/golden",
        run_command=lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 100, output.getvalue(), "SSH transport notice"
        ),
    )
    with pytest.raises(HostControlLocalError) as failure:
        restore_host_packages(control, declaration, secrets=("private-token",))
    error = failure.value
    assert error.exit_code == 100
    assert f"operation={operation}" in str(error)
    assert json.dumps(packages) in str(error)
    assert "E: held packages [REDACTED]" in error.stderr
    assert "download [REDACTED]" in error.stdout
    assert "private-token" not in str(error)
    assert len(error.stdout) <= MACHINE_QA_DIAGNOSTIC_LIMIT
    assert len(error.stderr) <= MACHINE_QA_DIAGNOSTIC_LIMIT
