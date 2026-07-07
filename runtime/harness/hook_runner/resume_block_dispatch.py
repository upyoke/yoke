"""Subprocess wrapper for the slim resume block renderer.

Kept as a sibling of ``session_dispatch.py`` so the dispatch module
stays under the 350-line cap while keeping the harness-side surface
inside the hook-runner package. The actual renderer + marker emission
live in ``yoke_core.domain.sessions_resume_block``.
"""

from __future__ import annotations

import subprocess

from runtime.harness.hook_runner.service_client import target_process_env


def render(root: str, session_id: str, harness_event: str) -> str:
    """Return the slim resume block (or empty string on miss / error)."""
    if not session_id:
        return ""
    cmd = [
        "python3", "-m", "yoke_core.domain.sessions_resume_block",
        "--session-id", session_id,
        "--harness-event", harness_event,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, cwd=root,
            env=target_process_env(root), timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return r.stdout if r.returncode == 0 else ""


__all__ = ["render"]
