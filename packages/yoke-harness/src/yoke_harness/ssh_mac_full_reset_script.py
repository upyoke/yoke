"""Guaranteed-macOS-primitive program for the dedicated Test Mac reset."""

from __future__ import annotations

import shlex

from yoke_cli.config.path_doctor import resolve_path_state_contract

from yoke_harness._ssh_mac_full_reset_script_body import SCRIPT_BODY
from yoke_harness.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    FULL_RESET_MARKER,
    FullResetPathContract,
    HOMEBREW_PATH,
    LEGACY_BASELINE_BEGIN,
    LEGACY_BASELINE_END,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
    RESET_RECOVERY_FAILURE_MARKER,
    RESET_RELATIVE_DIRECTORIES,
    RESET_TEMP_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    TOKEN_BACKUP_DIRECTORY,
    TOKEN_LOCATIONS,
    resolve_full_reset_path_contract,
)


def _array(values: tuple[str, ...]) -> str:
    return "(" + shlex.join(values) + ")"


def render_full_reset_script(contract: FullResetPathContract) -> str:
    """Render the reset program from one validated product PATH contract."""
    return "\n".join(
        (
            "#!/bin/zsh",
            "set -eu",
            "setopt PIPE_FAIL",
            "umask 077",
            f"full_reset_marker={shlex.quote(FULL_RESET_MARKER)}",
            f"token_backup_name={shlex.quote(TOKEN_BACKUP_DIRECTORY)}",
            f"evidence_source_suffix={shlex.quote(EVIDENCE_SOURCE_PATH)}",
            f"retained_evidence_name={shlex.quote(RETAINED_EVIDENCE_DIRECTORY)}",
            f"homebrew_path={shlex.quote(HOMEBREW_PATH)}",
            f"shell_path={shlex.quote(contract.shell_path)}",
            f"tool_bin_suffix={shlex.quote(contract.tool_bin_suffix)}",
            "tool_bin_home_reference="
            + shlex.quote(f"$HOME/{contract.tool_bin_suffix}"),
            f"managed_begin={shlex.quote(contract.managed_begin)}",
            f"managed_end={shlex.quote(contract.managed_end)}",
            f"legacy_baseline_begin={shlex.quote(LEGACY_BASELINE_BEGIN)}",
            f"legacy_baseline_end={shlex.quote(LEGACY_BASELINE_END)}",
            f"reset_failure_prefix={shlex.quote(RESET_FAILURE_PREFIX)}",
            "reset_recovery_failure_marker="
            + shlex.quote(RESET_RECOVERY_FAILURE_MARKER),
            *(
                f"reset_phase_{name}={shlex.quote(value)}"
                for name, value in RESET_PHASES.items()
            ),
            f"tools={_array(contract.tools)}",
            f"reset_relative_directories={_array(RESET_RELATIVE_DIRECTORIES)}",
            f"tool_file_suffixes={_array(contract.tool_file_suffixes)}",
            f"reset_temp_files={_array(RESET_TEMP_FILES)}",
            f"startup_file_suffixes={_array(contract.startup_file_suffixes)}",
            f"stage_source={shlex.quote(TOKEN_LOCATIONS[0][0])}",
            f"stage_backup_name={shlex.quote(TOKEN_LOCATIONS[0][1])}",
            f"prod_source={shlex.quote(TOKEN_LOCATIONS[1][0])}",
            f"prod_backup_name={shlex.quote(TOKEN_LOCATIONS[1][1])}",
            SCRIPT_BODY.lstrip(),
        )
    )


_REFERENCE_PATH_STATE = resolve_path_state_contract(
    env={"HOME": "/", "SHELL": "/bin/zsh"}
)
FULL_RESET_SCRIPT = render_full_reset_script(
    resolve_full_reset_path_contract(_REFERENCE_PATH_STATE)
)


__all__ = ["FULL_RESET_SCRIPT", "render_full_reset_script"]
