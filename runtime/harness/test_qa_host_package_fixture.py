"""Package fixtures undo complete mission deltas, including transitive installs."""

import contextlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness.qa_host_package_fixture import (
    _PACKAGE_SCRIPT,
    restore_host_packages,
)


def _execute(monkeypatch, journal, inventory, mode, declaration=None):
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
    assert inventory == {"tmux": "3.4"}


def test_declaration_on_unsupported_host_refuses_before_any_command():
    control = SimpleNamespace(os="macos")
    with pytest.raises(ValueError, match="os_package_fixture_unsupported"):
        restore_host_packages(control, {"os_packages": {"absent": ["python3-venv"]}})
