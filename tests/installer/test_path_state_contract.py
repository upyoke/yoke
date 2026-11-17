"""Bash login-file selection in the resolved PATH state contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.shell_path_state import resolve_path_state_contract


def _startup_file(home: Path) -> str:
    env = {"HOME": str(home), "SHELL": "/bin/bash"}
    return resolve_path_state_contract(target="posix", env=env, home=home).startup_file


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        ((".bash_profile", ".bash_login", ".profile"), ".bash_profile"),
        ((".bash_login", ".profile"), ".bash_login"),
        ((".profile",), ".profile"),
        ((), ".profile"),
    ],
)
def test_bash_startup_file_follows_login_read_order(tmp_path, present, expected):
    for name in present:
        (tmp_path / name).write_text("")
    assert _startup_file(tmp_path) == str(tmp_path / expected)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_posix_host_contract_uses_posix_rules_on_any_controller(monkeypatch, platform):
    monkeypatch.setattr("yoke_contracts.shell_path_state.sys.platform", platform)
    contract = resolve_path_state_contract(
        env={"HOME": "/Users/tester", "SHELL": "/bin/zsh"}, target="posix"
    )
    assert contract.home == "/Users/tester"
    assert contract.shell == "zsh"
    assert contract.tool_bin_dir == "/Users/tester/.local/bin"
    assert contract.yoke_bin == "/Users/tester/.local/bin/yoke"
    assert contract.startup_file == "/Users/tester/.zprofile"
    assert contract.ssh_startup_file == "/Users/tester/.zshenv"
    assert contract.posix_paths is True
