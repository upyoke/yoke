"""SSH adapter coverage for test-machine QA."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import path_doctor
from yoke_core.domain.host_control_runner import (
    TestMachineMaterial as MachineMaterial,
)
from yoke_core.domain.ssh_mac_full_reset_contract import (
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_RESTORED_ENTRIES_PREFIX,
    resolve_full_reset_path_contract,
)

GOLDEN_BASELINE_PATH = "/Users/Shared/yoke-golden/tester-home"
from yoke_core.domain.ssh_mac_full_reset_script import (
    FULL_RESET_SCRIPT,
    render_full_reset_script,
)
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


def test_ssh_adapter_uses_secret_file_reference_not_secret_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=0,
                stdout="/Users/tester\n/bin/zsh\n\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    key_path = tmp_path / "ssh_private_key"
    key_path.write_text("top-secret", encoding="utf-8")
    material = MachineMaterial(
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
            "golden_baseline_path": GOLDEN_BASELINE_PATH,
        },
        secrets={"ssh_private_key": "top-secret"},
        secret_paths={"ssh_private_key": str(key_path)},
    )
    control = SshMacHostControl(material)
    assert control.check_connection().ok
    argv_text = json.dumps([call[0] for call in calls])
    assert str(key_path) in argv_text
    assert "top-secret" not in argv_text


def test_full_reset_ssh_path_never_invokes_remote_python_or_clt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        remote = str(argv[-1])
        if len(calls) == 1:
            stdout = "/Users/tester\n/bin/zsh\n\n"
        elif remote.startswith(FULL_RESET_REMOTE_PATH):
            stdout = "\n".join(
                (
                    f"{RESET_RESTORED_ENTRIES_PREFIX}22",
                    f"{RESET_PROCESS_REAPED_PREFIX}0",
                    f"{RESET_LOAD_AVERAGE_PREFIX}2.50",
                    FULL_RESET_MARKER,
                )
            )
        else:
            stdout = ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    key_path = tmp_path / "ssh_private_key"
    key_path.write_text("top-secret", encoding="utf-8")
    material = MachineMaterial(
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
            "golden_baseline_path": GOLDEN_BASELINE_PATH,
        },
        secrets={"ssh_private_key": "top-secret"},
        secret_paths={"ssh_private_key": str(key_path)},
    )

    result = SshMacHostControl(material).reset_installer_test_host()

    assert result.ok
    remote_commands = [str(argv[-1]) for argv, _kwargs in calls]
    assert all("python" not in command.casefold() for command in remote_commands)
    assert all("CommandLineTools" not in command for command in remote_commands)
    uploads = [kwargs.get("input") for _argv, kwargs in calls if kwargs.get("input")]
    assert uploads == [FULL_RESET_SCRIPT]
    assert "top-secret" not in repr(calls)


def test_ssh_host_facts_drive_xdg_launcher_reset_and_entry_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    xdg_bin_home = "/Users/tester/Library/Yoke Bin"

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        remote = str(argv[-1])
        if len(calls) == 1:
            stdout = f"/Users/tester\n/bin/bash\n{xdg_bin_home}\n"
        elif remote.startswith(FULL_RESET_REMOTE_PATH):
            stdout = "\n".join(
                (
                    f"{RESET_RESTORED_ENTRIES_PREFIX}22",
                    f"{RESET_PROCESS_REAPED_PREFIX}0",
                    f"{RESET_LOAD_AVERAGE_PREFIX}1.05",
                    FULL_RESET_MARKER,
                )
            )
        else:
            stdout = ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    key_path = tmp_path / "ssh_private_key"
    key_path.write_text("top-secret", encoding="utf-8")
    control = SshMacHostControl(
        MachineMaterial(
            project_id=1,
            project="yoke",
            settings={
                "resource_name": "mac-mini-lab",
                "host": "test-mac.local",
                "user": "yoke-test",
                "operating_notes": "",
                "golden_baseline_path": GOLDEN_BASELINE_PATH,
            },
            secrets={"ssh_private_key": "top-secret"},
            secret_paths={"ssh_private_key": str(key_path)},
        )
    )

    assert control.path_state.tool_bin_dir == xdg_bin_home
    home = Path("/Users/tester")
    assert control.path_state.startup_file == str(
        path_doctor.default_startup_file("bash", home)
    )
    assert control.path_state.ssh_startup_file == str(
        path_doctor.default_ssh_startup_file("bash", home)
    )
    assert control._resolve_entry_surface("{yoke_bin} status") == (
        "'/Users/tester/Library/Yoke Bin/yoke' status"
    )
    fixture = control.create_fixture_operation_runner()
    assert fixture._yoke_bin() == f"{xdg_bin_home}/yoke"
    result = control.reset_installer_test_host()

    assert result.ok
    expected_script = render_full_reset_script(
        resolve_full_reset_path_contract(control.path_state)
    )
    uploads = [kwargs.get("input") for _argv, kwargs in calls if kwargs.get("input")]
    assert uploads == [expected_script]
    assert result.evidence["path_state"]["tool_bin_dir"] == xdg_bin_home
    assert result.evidence["path_state"]["launcher"] == (f"{xdg_bin_home}/yoke")


def test_fixture_file_transfers_use_guaranteed_mac_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        remote = str(argv[-1])
        if len(calls) == 1:
            stdout = "/Users/tester\n/bin/zsh\n\n"
        elif '/usr/bin/base64 < "$target"' in remote:
            stdout = base64.b64encode(b"existing fixture").decode("ascii") + "\n"
        else:
            stdout = ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    key_path = tmp_path / "ssh_private_key"
    key_path.write_text("top-secret", encoding="utf-8")
    control = SshMacHostControl(
        MachineMaterial(
            project_id=1,
            project="yoke",
            settings={
                "resource_name": "mac-mini-lab",
                "host": "test-mac.local",
                "user": "yoke-test",
                "operating_notes": "",
                "golden_baseline_path": GOLDEN_BASELINE_PATH,
            },
            secrets={"ssh_private_key": "top-secret"},
            secret_paths={"ssh_private_key": str(key_path)},
        )
    )

    assert control.read_text("/Users/tester/fixture.txt") == "existing fixture"
    control.write_text("/Users/tester/fixture.txt", "replacement fixture")

    remote_commands = [str(argv[-1]) for argv, _kwargs in calls]
    assert all("python" not in command.casefold() for command in remote_commands)
    assert any("/usr/bin/base64 <" in command for command in remote_commands)
    assert any("/usr/bin/base64 -D" in command for command in remote_commands)
    uploads = [kwargs.get("input") for _argv, kwargs in calls if kwargs.get("input")]
    assert uploads == [
        base64.b64encode(b"replacement fixture").decode("ascii"),
    ]
    assert "top-secret" not in repr(calls)
