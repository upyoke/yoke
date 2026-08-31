"""Rendered-program contract coverage for the dedicated Test Mac restore."""

from __future__ import annotations

from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    run_zsh_syntax_if_available,
)
from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset_contract import (
    FULL_DISK_ACCESS_PROBE_PATH,
    FULL_RESET_MARKER,
    PRESERVED_HOME_ENTRIES,
    STARTUP_FILE_NAMES,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_TEMP_FILES,
    golden_baseline_clears_home,
    resolve_full_reset_path_contract,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT
from yoke_harness.ssh_mac_full_reset_script import (
    preserved_levels,
    render_full_reset_script,
    render_level_functions,
)


def test_rendered_program_restores_a_baseline_rather_than_enumerating_residue() -> None:
    assert STARTUP_FILE_NAMES == tuple(
        str(path.relative_to("/"))
        for path in path_doctor.supported_startup_files(Path("/"))
    )
    assert FULL_DISK_ACCESS_PROBE_PATH in FULL_RESET_SCRIPT
    assert "assert_full_disk_access" in FULL_RESET_SCRIPT
    assert 'run_reset_step "$reset_phase_restore_golden" restore_golden' in (
        FULL_RESET_SCRIPT
    )
    assert FULL_RESET_MARKER in FULL_RESET_SCRIPT
    # The enumeration the restore replaces is gone, not merely bypassed, and so
    # is the smoke-token machinery it carried.
    for retired in (
        "remove_registered_state",
        "clean_startup_files",
        "uninstall_homebrew_uv",
        "preserve_tokens",
        "restore_tokens",
        "yoke-smoke-tokens",
        "/tmp/yoke-stage.token",
        "/opt/homebrew",
        "YOKE TEST HOST BASELINE",
    ):
        assert retired not in FULL_RESET_SCRIPT, retired
    assert run_zsh_syntax_if_available(FULL_RESET_SCRIPT) in (None,) or (
        run_zsh_syntax_if_available(FULL_RESET_SCRIPT).returncode == 0
    )


def test_preserved_levels_descend_exactly_as_far_as_a_protected_ancestor() -> None:
    assert preserved_levels() == (
        ("", (".ssh", "Library")),
        ("Library", ("Application Support",)),
        ("Library/Application Support", ("com.apple.TCC",)),
    )


def test_clear_and_restore_walk_the_same_levels_and_keep_the_same_names() -> None:
    rendered = render_level_functions(preserved_levels())
    clear, separator, restore = rendered.partition("restore_golden_levels() {")
    assert separator
    clear_levels = [line for line in clear.splitlines() if "/usr/bin/find" in line]
    restore_levels = [line for line in restore.splitlines() if "/usr/bin/find" in line]
    restore_calls = [
        line for line in restore.splitlines() if 'restore_entry "$captured"' in line
    ]
    # Symmetry is the invariant: flattening either walk lets the captured copy
    # of a preserved path overwrite the live one.
    assert (
        len(clear_levels)
        == len(restore_levels)
        == len(restore_calls)
        == len(preserved_levels())
    )
    for clear_line, restore_line, (_directory, names) in zip(
        clear_levels, restore_levels, preserved_levels()
    ):
        for name in names:
            assert f"-not -name {name!r}".replace('"', "'") in clear_line or (
                name in clear_line
            )
            assert name in restore_line
        assert "/bin/rm -rf" in clear_line
    assert "/bin/cp -Rpf" in FULL_RESET_SCRIPT
    assert '/bin/chmod -RN "$destination"' in FULL_RESET_SCRIPT
    # Restore records why it failed; the clear tolerates cosmetic ACL refusals.
    assert all('2>>"$restore_error_log"' in line for line in restore_calls)
    assert all("2>/dev/null" in line for line in clear_levels)


def test_preserved_and_absent_surfaces_are_reachable_from_the_program() -> None:
    assert PRESERVED_HOME_ENTRIES == (
        ".ssh",
        "Library/Application Support/com.apple.TCC",
    )
    assert ".yoke" in YOKE_ABSENT_RELATIVE_DIRECTORIES
    assert YOKE_ABSENT_TEMP_FILES == ("/tmp/yoke-install",)
    for suffix in PRESERVED_HOME_ENTRIES:
        assert suffix in FULL_RESET_SCRIPT


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
