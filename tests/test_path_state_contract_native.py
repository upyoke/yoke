"""Local-path and explicit POSIX behavior for the PATH state contract."""

import pytest

from pathlib import Path

from yoke_contracts.shell_path_state import resolve_path_state_contract
from yoke_contracts.ssh_mac_full_reset_path_state import (
    canonical_posix_path_state_contract,
)


@pytest.mark.posix_only(reason="runs on the POSIX test machine")
def test_local_contract_observes_existing_bash_profile(tmp_path: Path) -> None:
    profile = tmp_path / ".bash_profile"
    profile.touch()

    contract = resolve_path_state_contract(
        target="posix", home=tmp_path, env={"HOME": str(tmp_path), "SHELL": "/bin/bash"}
    )

    assert contract.startup_file == str(profile)
    assert contract.posix_paths is True


def test_reset_fixture_explicitly_uses_posix_paths() -> None:
    contract = canonical_posix_path_state_contract()

    assert contract.posix_paths is True
    assert contract.tool_bin_dir == "/.local/bin"
    assert contract.yoke_bin == "/.local/bin/yoke"
    assert all("\\" not in path for path in contract.supported_startup_files)


@pytest.mark.parametrize("client", ["win32", "darwin", "linux"])
def test_remote_posix_contract_ignores_client_platform(monkeypatch, client):
    from yoke_contracts import shell_path_state

    monkeypatch.setattr(shell_path_state.sys, "platform", client)
    contract = resolve_path_state_contract(
        target="posix",
        env={
            "HOME": "/Users/tester",
            "SHELL": "/bin/zsh",
            "XDG_BIN_HOME": "/Users/tester/tools",
        },
    )
    assert contract.home == "/Users/tester"
    assert contract.shell_path == "/bin/zsh"
    assert contract.startup_file == "/Users/tester/.zprofile"
    assert contract.ssh_startup_file == "/Users/tester/.zshenv"
    assert contract.yoke_bin == "/Users/tester/tools/yoke"
    assert all("\\" not in path for path in contract.tool_paths)


@pytest.mark.parametrize("client", ["win32", "darwin", "linux"])
def test_explicit_posix_target_keeps_shell_with_observed_home(tmp_path, monkeypatch, client):
    from yoke_contracts import shell_path_state

    monkeypatch.setattr(shell_path_state.sys, "platform", client)
    contract = resolve_path_state_contract(
        target="posix", home=tmp_path,
        env={"HOME": str(tmp_path), "SHELL": "/bin/bash"},
    )
    assert contract.shell == "bash"
