"""Rendered-program contract coverage for the dedicated Test Machine restore."""

from __future__ import annotations

from yoke_harness.ssh_mac_preserved_state import OS_MANAGED_HOME_ENTRIES

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    run_zsh_syntax_if_available,
)
from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset_contract import (
    PRESERVED_HOME_ENTRIES,
    STARTUP_FILE_NAMES,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_TEMP_FILES,
    canonical_full_reset_path_contract,
    golden_baseline_clears_home,
    resolve_full_reset_path_contract,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT
from yoke_harness.ssh_mac_full_reset_script import (
    preserved_levels,
    render_full_reset_script,
)


def test_startup_file_contract_and_rendered_program_syntax() -> None:
    assert STARTUP_FILE_NAMES == (
        ".zprofile",
        ".zshenv",
        ".zshrc",
        ".zlogin",
        ".bashrc",
        ".bash_profile",
        ".bash_login",
        ".profile",
        ".config/fish/config.fish",
    )
    syntax = run_zsh_syntax_if_available(FULL_RESET_SCRIPT)
    assert syntax is None or syntax.returncode == 0, syntax.stderr if syntax else ""


def test_reference_reset_contract_is_host_independent_posix_state() -> None:
    contract = canonical_full_reset_path_contract()
    assert contract.home == "/"
    assert contract.shell_path == "/bin/zsh"
    assert contract.launcher_path == "/.local/bin/yoke"
    assert all("\\" not in path for path in contract.tool_file_suffixes)
    assert all("\\" not in path for path in contract.startup_file_suffixes)


def test_preserved_levels_descend_exactly_as_far_as_a_protected_ancestor() -> None:
    assert preserved_levels((".ssh", "Library/Application Support/com.apple.TCC")) == (
        ("", (".ssh", "Library")),
        ("Library", ("Application Support",)),
        ("Library/Application Support", ("com.apple.TCC",)),
    )


def test_preserved_and_absent_surface_contract() -> None:
    assert PRESERVED_HOME_ENTRIES == (
        ".ssh",
        "Library/Application Support/com.apple.TCC",
        "Library/Keychains",
        ".claude/.credentials.json",
        ".codex/auth.json",
        *OS_MANAGED_HOME_ENTRIES,
        ".yoke-browser-identities",
        "Library/Containers/com.apple.Safari/Data/Library/Cookies",
    )
    assert ".yoke" in YOKE_ABSENT_RELATIVE_DIRECTORIES
    assert YOKE_ABSENT_TEMP_FILES == ("/tmp/yoke-install",)


def test_golden_baseline_must_survive_the_clear_it_drives() -> None:
    home = "/Users/tester"
    assert golden_baseline_clears_home("/Users/Shared/yoke-golden/home", home=home)
    for rejected in (
        "/Users/tester",
        "/Users/tester/golden",
        "/Users/tester/Library/golden",
        "relative/golden",
        "/Users/Shared/../tester/golden",
        "",
    ):
        assert not golden_baseline_clears_home(rejected, home=home), rejected


def test_rendered_program_stays_inside_one_explicit_home_for_any_shell() -> None:
    contract = resolve_full_reset_path_contract(
        path_doctor.resolve_path_state_contract(
            env={
                "HOME": "/Users/tester",
                "SHELL": "/bin/bash",
                "XDG_BIN_HOME": "/Users/tester/.custom/bin",
            }
        )
    )
    script = render_full_reset_script(contract)
    assert "/Users/tester" not in script
    assert contract.tool_bin_suffix == ".custom/bin"
    syntax = run_zsh_syntax_if_available(script)
    assert syntax is None or syntax.returncode == 0, syntax.stderr if syntax else ""
