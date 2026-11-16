"""Validate a candidate helper in isolation before release publication."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile

from yoke_cli.config import github_git_credential_bundle as bundle
from yoke_contracts.refusal_recovery import compose_refusal


def check_candidate(config_path: str | Path | None = None) -> dict[str, object]:
    """Exercise the complete bundled launcher using the candidate interpreter."""
    try:
        python = Path(sys.executable)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise RuntimeError(
                f"candidate interpreter is missing or not executable: {python}"
            )
        with tempfile.TemporaryDirectory(prefix="yoke-helper-check-") as directory:
            helper = bundle.install(Path(directory) / "helper")
            result = subprocess.run(
                [str(python), "-I", str(helper), "store"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    result.stderr or result.stdout or "helper exited without output"
                )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "checked": False,
            "error": compose_refusal(
                f"github_helper_candidate_invalid: {exc}",
                recovery="rerun the public installer or yoke update with a working release",
            ),
        }
    from yoke_cli.config.github_repo_helper_reconnect import restore_missing_bundle

    receipt = restore_missing_bundle(config_path, check_only=True)
    if receipt.get("error"):
        return {
            "checked": False,
            "error": compose_refusal(
                f"github_helper_candidate_invalid: {receipt['error']}",
                recovery="repair the named checkout or machine config, then retry yoke update",
            ),
        }
    return {"checked": True}
