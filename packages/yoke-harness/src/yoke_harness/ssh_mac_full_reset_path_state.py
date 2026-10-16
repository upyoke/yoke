"""Host-independent POSIX shell state used by the macOS reset renderer."""

from __future__ import annotations

from pathlib import PurePosixPath

from yoke_cli.config.path_doctor import (
    HARNESS_CLIS,
    MANAGED_BEGIN,
    MANAGED_END,
    TOOLS,
    PathStateContract,
)


def canonical_posix_path_state_contract() -> PathStateContract:
    """Build reset paths without consulting or interpreting the local host."""
    home = PurePosixPath("/")
    tool_bin = home / ".local" / "bin"
    return PathStateContract(
        home=str(home),
        shell="zsh",
        shell_path="/bin/zsh",
        tool_bin_dir=str(tool_bin),
        startup_file=str(home / ".zprofile"),
        ssh_startup_file=str(home / ".zshenv"),
        supported_startup_files=tuple(
            str(home / suffix)
            for suffix in (
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
        ),
        managed_begin=MANAGED_BEGIN,
        managed_end=MANAGED_END,
        tools=TOOLS,
        harness_clis=HARNESS_CLIS,
        tool_paths=tuple(str(tool_bin / tool) for tool in TOOLS),
        yoke_bin=str(tool_bin / "yoke"),
        posix_paths=True,
    )


__all__ = ["canonical_posix_path_state_contract"]
