"""Client-side paths and product-derived shell state for the Test Mac reset.

The reset restores one captured golden home rather than enumerating residue to
delete. Enumeration cannot be proven complete, and a host that is only mostly
clean is indistinguishable from one that is clean, so the product-derived Yoke
paths below no longer name deletion targets: they name what must be ABSENT once
the golden is back. Being incomplete is safe in a verifier and fatal in a
destroyer, which is the whole reason the direction was reversed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from yoke_cli.config.path_doctor import (
    PathStateContract,
    SUPPORTED_SHELLS,
    resolve_path_state_contract,
)


FULL_RESET_MARKER = "YOKE_MAC_WIPE_OK"
FULL_RESET_REMOTE_PATH = "/tmp/yoke-machine-qa-full-reset.zsh"
RESET_FAILURE_PREFIX = "YOKE_RESET_FAILED_"
RESET_RECOVERY_FAILURE_MARKER = "YOKE_RESET_RECOVERY_FAILED"
RESET_PHASES = {
    "validate_home": "VALIDATE_HOME",
    "assert_full_disk_access": "ASSERT_FULL_DISK_ACCESS",
    "validate_golden": "VALIDATE_GOLDEN",
    "reap_processes": "REAP_PROCESSES",
    "clear_home": "CLEAR_HOME",
    "restore_golden": "RESTORE_GOLDEN",
    "verify_restored_home": "VERIFY_RESTORED_HOME",
    "emit_outcomes": "EMIT_OUTCOMES",
    "recovery": "RECOVERY",
    "complete": "COMPLETE",
}

# Full Disk Access gate. The system privacy database always exists on macOS,
# sits outside every user home, and opens only for a process that holds the
# grant, so reading it tests the grant itself rather than the channel carrying
# the command. A channel test would pass on a host whose grant was later
# revoked, which is the same silent partial restore in a new disguise: without
# the grant an identical restore skipped 8,389 entries across privacy-protected
# Library subtrees and reported success.
FULL_DISK_ACCESS_PROBE_PATH = "/Library/Application Support/com.apple.TCC/TCC.db"

# Kept verbatim through the clear, each at the depth it lives:
#   .ssh                                   the restore is driven over the very
#                                          channel a naive clear destroys, and
#                                          between clear and restore the host
#                                          would otherwise have no way back in;
#   Library/Application Support/com.apple.TCC
#                                          System Integrity Protection owns the
#                                          user privacy database and its grants
#                                          can only be re-established by a
#                                          person clicking in the GUI, so the
#                                          live copy outranks any captured one.
PRESERVED_HOME_ENTRIES = (
    ".ssh",
    "Library/Application Support/com.apple.TCC",
)

# Sibling artifacts named from the golden directory itself, so a second golden
# never collides with the first and neither one contaminates the home it holds.
GOLDEN_MANIFEST_SUFFIX = ".manifest"
GOLDEN_PROBES_SUFFIX = ".probes"

RESET_TOOL_AUXILIARY_FILES = ("env",)
INSTALLER_TEMP_PATH = "/tmp/yoke-install"
# Home-relative Yoke and uv state asserted absent after the restore. The golden
# was captured with zero Yoke on it, so any of these reappearing means the
# restore did not take.
YOKE_ABSENT_RELATIVE_DIRECTORIES = (
    ".yoke",
    ".yoke-e2e-logs",
    ".local/share/uv",
    ".local/state/uv",
    ".cache/uv",
    ".config/uv",
    "Library/Caches/uv",
    "Library/Application Support/uv",
    "Library/Application Support/yoke",
)
YOKE_ABSENT_TEMP_FILES = (INSTALLER_TEMP_PATH,)
RESET_REAP_MARKER_ANCHOR = "/tmp/yoke-qa-"
RESET_REAP_MARKER_SUFFIX = ".exit"
RESET_REAP_ONBOARD_ANCHOR = "onboard --post-install"
RESET_PROCESS_REAPED_PREFIX = "YOKE_RESET_PROCESS_TABLE_REAPED_"
RESET_LOAD_AVERAGE_PREFIX = "YOKE_RESET_LOAD_AVERAGE_"
RESET_RESTORED_ENTRIES_PREFIX = "YOKE_RESET_RESTORED_ENTRIES_"


@dataclass(frozen=True)
class FullResetPathContract:
    """Home-relative Yoke surfaces resolved from product PATH authority."""

    home: str
    shell_path: str
    tool_bin_dir: str
    tool_bin_suffix: str
    tool_file_suffixes: tuple[str, ...]
    startup_file_suffixes: tuple[str, ...]
    launcher_path: str
    managed_begin: str
    managed_end: str
    tools: tuple[str, ...]

    @property
    def tool_file_paths(self) -> tuple[str, ...]:
        home = PurePosixPath(self.home)
        return tuple(str(home / suffix) for suffix in self.tool_file_suffixes)

    @property
    def startup_files(self) -> tuple[str, ...]:
        home = PurePosixPath(self.home)
        return tuple(str(home / suffix) for suffix in self.startup_file_suffixes)


def _relative_home_target(path: str, *, home: PurePosixPath) -> str:
    selected = PurePosixPath(path)
    if (
        not selected.is_absolute()
        or ".." in selected.parts
        or selected == home
        or home not in selected.parents
    ):
        raise ValueError("reset target escapes the explicit Test Mac home")
    return str(selected.relative_to(home))


def resolve_full_reset_path_contract(
    path_state: PathStateContract,
) -> FullResetPathContract:
    """Close every product-owned Yoke path below one explicit host home."""
    home = PurePosixPath(path_state.home)
    shell_path = PurePosixPath(path_state.shell_path)
    if (
        not home.is_absolute()
        or ".." in home.parts
        or not shell_path.is_absolute()
        or shell_path.name != path_state.shell
        or path_state.shell not in SUPPORTED_SHELLS
    ):
        raise ValueError("reset PATH state contains unsafe host facts")

    tool_files = (
        *path_state.tool_paths,
        *(
            str(PurePosixPath(path_state.tool_bin_dir) / name)
            for name in RESET_TOOL_AUXILIARY_FILES
        ),
    )
    tool_file_suffixes = tuple(
        _relative_home_target(path, home=home) for path in tool_files
    )
    startup_file_suffixes = tuple(
        _relative_home_target(path, home=home)
        for path in path_state.supported_startup_files
    )
    tool_bin_suffix = _relative_home_target(path_state.tool_bin_dir, home=home)
    return FullResetPathContract(
        home=str(home),
        shell_path=str(shell_path),
        tool_bin_dir=path_state.tool_bin_dir,
        tool_bin_suffix=tool_bin_suffix,
        tool_file_suffixes=tool_file_suffixes,
        startup_file_suffixes=startup_file_suffixes,
        launcher_path=path_state.yoke_bin,
        managed_begin=path_state.managed_begin,
        managed_end=path_state.managed_end,
        tools=path_state.tools,
    )


def golden_baseline_clears_home(golden_baseline_path: str, *, home: str) -> bool:
    """Reject a golden that the clear it drives would itself destroy.

    Storing the baseline inside the home makes the restore self-consuming, so
    the containment rule is enforced against the live home rather than against
    a settings document that cannot know it.
    """
    selected = PurePosixPath(golden_baseline_path)
    resolved_home = PurePosixPath(home)
    return (
        selected.is_absolute()
        and ".." not in selected.parts
        and golden_baseline_path == str(selected)
        and len(selected.parts) >= 3
        and selected != resolved_home
        and resolved_home not in selected.parents
    )


_REFERENCE_PATH_STATE = resolve_path_state_contract(
    env={"HOME": "/", "SHELL": "/bin/zsh"}
)
_REFERENCE_RESET_PATHS = resolve_full_reset_path_contract(_REFERENCE_PATH_STATE)
YOKE_ABSENT_RELATIVE_FILES = _REFERENCE_RESET_PATHS.tool_file_suffixes
STARTUP_FILE_NAMES = _REFERENCE_RESET_PATHS.startup_file_suffixes


__all__ = [
    "FULL_DISK_ACCESS_PROBE_PATH",
    "FULL_RESET_MARKER",
    "FULL_RESET_REMOTE_PATH",
    "FullResetPathContract",
    "GOLDEN_MANIFEST_SUFFIX",
    "GOLDEN_PROBES_SUFFIX",
    "INSTALLER_TEMP_PATH",
    "PRESERVED_HOME_ENTRIES",
    "RESET_FAILURE_PREFIX",
    "RESET_LOAD_AVERAGE_PREFIX",
    "RESET_PHASES",
    "RESET_PROCESS_REAPED_PREFIX",
    "RESET_REAP_MARKER_ANCHOR",
    "RESET_REAP_MARKER_SUFFIX",
    "RESET_REAP_ONBOARD_ANCHOR",
    "RESET_RECOVERY_FAILURE_MARKER",
    "RESET_RESTORED_ENTRIES_PREFIX",
    "RESET_TOOL_AUXILIARY_FILES",
    "STARTUP_FILE_NAMES",
    "YOKE_ABSENT_RELATIVE_DIRECTORIES",
    "YOKE_ABSENT_RELATIVE_FILES",
    "YOKE_ABSENT_TEMP_FILES",
    "golden_baseline_clears_home",
    "resolve_full_reset_path_contract",
]
