"""Resolve a checkout's Git identity before Docker excludes its metadata."""

from pathlib import Path
import re
import subprocess


def identity(checkout_path: str) -> tuple[str, str]:
    """Return the real source commit and a PEP 440 snapshot wheel version."""
    root = Path(checkout_path).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "checkout_build_identity_unavailable: cannot read Git HEAD; "
            "repair or commit the checkout, then retry the core build"
        ) from exc
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(
            "checkout_build_identity_invalid: Git HEAD is not a full source commit; "
            "repair the checkout, then retry the core build"
        )
    return commit, f"0.dev0+g{commit[:12]}"
