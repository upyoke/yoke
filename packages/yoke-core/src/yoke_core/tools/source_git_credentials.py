"""Bind config-specific Git credential helpers to a source command's snapshot."""

from pathlib import Path
import subprocess
from typing import Mapping

from yoke_contracts.git_credential_command import rebind_helper


def snapshot_git_helpers(
    env: Mapping[str, str], selected: Path, snapshot: Path
) -> dict[str, str]:
    """Replay the effective helper chain in a child-only Git config overlay."""
    resolved = dict(env)
    result = subprocess.run(
        ["git", "config", "--null", "--get-regexp", r"^credential(\..*)?\.helper$"],
        env=resolved,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 1:  # No configured helper.
        return resolved
    if result.returncode:
        raise OSError("cannot inspect Git credential helpers for source isolation")
    helpers = [
        tuple(record.split("\n", 1)) for record in result.stdout.split("\0") if record
    ]
    rebound = [
        (key, rebind_helper(value, selected, snapshot)) for key, value in helpers
    ]
    if rebound == helpers:
        return resolved
    # A generic reset clears earlier matching helpers. Replaying every entry in
    # order retains URL matching, user helpers and explicit empty resets.
    # Git reads command-line parameters after GIT_CONFIG_COUNT. Append here so
    # inherited `git -c` helpers cannot restore the original config afterward.
    parameters = []
    for key, value in [("credential.helper", ""), *rebound]:
        parameter = (key + "=" + value).replace("'", "'\\''")
        parameters.append("'" + parameter + "'")
    resolved["GIT_CONFIG_PARAMETERS"] = " ".join(
        [resolved.get("GIT_CONFIG_PARAMETERS", ""), *parameters]
    ).strip()
    return resolved
