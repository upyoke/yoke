"""Local-path and explicit POSIX behavior for the PATH state contract."""

from pathlib import Path

from yoke_cli.config.path_state_contract import resolve_path_state_contract
from yoke_harness.ssh_mac_full_reset_path_state import (
    canonical_posix_path_state_contract,
)


def test_local_contract_observes_existing_bash_profile(tmp_path: Path) -> None:
    profile = tmp_path / ".bash_profile"
    profile.touch()

    contract = resolve_path_state_contract(
        env={"HOME": str(tmp_path), "SHELL": "/bin/bash"}
    )

    assert contract.startup_file == str(profile)
    assert contract.posix_paths is False


def test_reset_fixture_explicitly_uses_posix_paths() -> None:
    contract = canonical_posix_path_state_contract()

    assert contract.posix_paths is True
    assert contract.tool_bin_dir == "/.local/bin"
    assert contract.yoke_bin == "/.local/bin/yoke"
    assert all("\\" not in path for path in contract.supported_startup_files)
