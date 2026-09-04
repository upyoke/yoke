"""Render the guaranteed-macOS-primitive golden-capture program."""

from __future__ import annotations

import shlex

from yoke_harness._ssh_mac_golden_capture_script_body import CAPTURE_SCRIPT_BODY
from yoke_harness.ssh_mac_full_reset_contract import (
    FULL_DISK_ACCESS_PROBE_PATH,
    FullResetPathContract,
    GOLDEN_MANIFEST_SUFFIX,
    GOLDEN_PROBES_SUFFIX,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_TEMP_FILES,
)
from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_ENTRIES_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_KILOBYTES_PREFIX,
    CAPTURE_MANIFEST_DIGEST_PREFIX,
    CAPTURE_PHASES,
    CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED,
    CAPTURE_REFUSAL_KIND_FOREIGN_OWNER,
    CAPTURE_REFUSAL_KIND_RESIDUE,
    CAPTURE_REFUSAL_PREFIX,
    GOLDEN_CAPTURE_MARKER,
    GOLDEN_DIRECTORY_MODE,
    GOLDEN_SIDECAR_MODE,
)


def _array(values: tuple[str, ...]) -> str:
    return "(" + " ".join(shlex.quote(value) for value in values) + ")"


def render_golden_capture_script(contract: FullResetPathContract) -> str:
    """Render the capture program from one validated product PATH contract.

    The declared-absent roster comes from the reset's own contract rather than
    a second list here: the residue a capture must refuse is exactly the
    residue a reset asserts gone, and two lists would drift into a baseline
    that captures what the reset then fails on.
    """
    return "\n".join(
        (
            "#!/bin/zsh",
            "set -eu",
            "setopt PIPE_FAIL",
            "umask 077",
            f"capture_marker={shlex.quote(GOLDEN_CAPTURE_MARKER)}",
            f"capture_failure_prefix={shlex.quote(CAPTURE_FAILURE_PREFIX)}",
            f"full_disk_access_probe={shlex.quote(FULL_DISK_ACCESS_PROBE_PATH)}",
            f"manifest_suffix={shlex.quote(GOLDEN_MANIFEST_SUFFIX)}",
            f"probes_suffix={shlex.quote(GOLDEN_PROBES_SUFFIX)}",
            f"golden_directory_mode={shlex.quote(GOLDEN_DIRECTORY_MODE)}",
            f"golden_sidecar_mode={shlex.quote(GOLDEN_SIDECAR_MODE)}",
            f"capture_entries_prefix={shlex.quote(CAPTURE_ENTRIES_PREFIX)}",
            f"capture_kilobytes_prefix={shlex.quote(CAPTURE_KILOBYTES_PREFIX)}",
            "capture_manifest_digest_prefix="
            + shlex.quote(CAPTURE_MANIFEST_DIGEST_PREFIX),
            f"refusal_prefix={shlex.quote(CAPTURE_REFUSAL_PREFIX)}",
            "refusal_kind_residue=" + shlex.quote(CAPTURE_REFUSAL_KIND_RESIDUE),
            "refusal_kind_foreign_owner="
            + shlex.quote(CAPTURE_REFUSAL_KIND_FOREIGN_OWNER),
            "refusal_kind_destination_occupied="
            + shlex.quote(CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED),
            *(
                f"capture_phase_{name}={shlex.quote(value)}"
                for name, value in CAPTURE_PHASES.items()
            ),
            f"yoke_absent_directories={_array(YOKE_ABSENT_RELATIVE_DIRECTORIES)}",
            f"yoke_absent_files={_array(contract.tool_file_suffixes)}",
            f"yoke_absent_temp_files={_array(YOKE_ABSENT_TEMP_FILES)}",
            CAPTURE_SCRIPT_BODY.lstrip(),
        )
    )


__all__ = ["render_golden_capture_script"]
