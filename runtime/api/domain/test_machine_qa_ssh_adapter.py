"""SSH adapter coverage for test-machine QA."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.host_control_executor import (
    TestMachineMaterial as MachineMaterial,
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
                stdout=json.dumps(
                    {
                        "home": "/Users/tester",
                        "shell": "/bin/zsh",
                        "xdg_bin_home": None,
                    }
                ),
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
        },
        secrets={
            "ssh_private_key": "top-secret",
            "sudo_password": "sudo-secret",
            "screen_control_token": "screen-secret",
        },
        secret_paths={"ssh_private_key": str(key_path)},
    )
    control = SshMacHostControl(material)
    assert control.check_connection().ok
    argv_text = json.dumps([call[0] for call in calls])
    assert str(key_path) in argv_text
    assert "top-secret" not in argv_text
    assert "sudo-secret" not in argv_text
    assert "screen-secret" not in argv_text
