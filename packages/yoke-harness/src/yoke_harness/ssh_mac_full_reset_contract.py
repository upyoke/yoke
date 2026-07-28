"""Client-side paths and product-derived shell state for the Test Mac reset."""

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
TOKEN_BACKUP_DIRECTORY = "yoke-smoke-tokens"
EVIDENCE_SOURCE_PATH = ".yoke/installer-smoke-evidence"
RETAINED_EVIDENCE_DIRECTORY = "yoke-smoke-evidence"
RESET_RELATIVE_DIRECTORIES = (
    ".yoke-e2e-logs",
    ".local/share/uv",
    ".local/state/uv",
    ".cache/uv",
    ".config/uv",
    "Library/Caches/uv",
    "Library/Application Support/uv",
    "Library/Application Support/yoke",
)
RESET_TOOL_AUXILIARY_FILES = ("env",)
INSTALLER_TEMP_PATH = "/tmp/yoke-install"
RESET_TEMP_FILES = (
    INSTALLER_TEMP_PATH,
    "/tmp/yoke-token",
)
TOKEN_LOCATIONS = (
    ("/tmp/yoke-stage.token", "yoke-stage.token", "STAGE"),
    ("/tmp/yoke-prod.token", "yoke-prod.token", "PROD"),
)
HOMEBREW_PATH = "/opt/homebrew/bin/brew"
LEGACY_BASELINE_BEGIN = "# >>> BEGIN YOKE TEST HOST BASELINE >>>"
LEGACY_BASELINE_END = "# <<< END YOKE TEST HOST BASELINE <<<"


@dataclass(frozen=True)
class FullResetPathContract:
    """Home-relative destructive targets resolved from product PATH authority."""

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
    """Close every destructive product path below one explicit host home."""
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


_REFERENCE_PATH_STATE = resolve_path_state_contract(
    env={"HOME": "/", "SHELL": "/bin/zsh"}
)
_REFERENCE_RESET_PATHS = resolve_full_reset_path_contract(_REFERENCE_PATH_STATE)
RESET_RELATIVE_FILES = _REFERENCE_RESET_PATHS.tool_file_suffixes
STARTUP_FILE_NAMES = _REFERENCE_RESET_PATHS.startup_file_suffixes


__all__ = [
    "EVIDENCE_SOURCE_PATH",
    "FULL_RESET_MARKER",
    "FULL_RESET_REMOTE_PATH",
    "FullResetPathContract",
    "HOMEBREW_PATH",
    "INSTALLER_TEMP_PATH",
    "LEGACY_BASELINE_BEGIN",
    "LEGACY_BASELINE_END",
    "RETAINED_EVIDENCE_DIRECTORY",
    "RESET_RELATIVE_DIRECTORIES",
    "RESET_RELATIVE_FILES",
    "RESET_TEMP_FILES",
    "RESET_TOOL_AUXILIARY_FILES",
    "STARTUP_FILE_NAMES",
    "TOKEN_BACKUP_DIRECTORY",
    "TOKEN_LOCATIONS",
    "resolve_full_reset_path_contract",
]
