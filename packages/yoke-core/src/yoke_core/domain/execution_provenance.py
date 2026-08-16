"""Resolve executing-code provenance for hook and guard verdicts.

Every deny/allow line should name which install served the decision so
version skew is a loud fingerprint, not a forensic reconstruction.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional


PROVENANCE_KEYS = ("source_sha", "install_kind", "install_path")


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    sha = (result.stdout or "").strip()
    return sha if result.returncode == 0 and sha else ""


def collect_execution_provenance(
    *,
    module_file: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Return ``{source_sha, install_kind, install_path}`` for this process."""
    environ = os.environ if env is None else env
    env_sha = (environ.get("YOKE_BUILD_SHA") or "").strip()
    path = Path(module_file or __file__).resolve()
    install_path = str(path)
    kind = "unknown"
    sha = env_sha
    for parent in (path, *path.parents):
        if (parent / ".git").exists() or (parent / ".git").is_file():
            kind = "source_checkout"
            install_path = str(parent)
            sha = sha or _git_sha(parent)
            break
        if parent.name in {"site-packages", "dist-packages"}:
            kind = "installed_wheel"
            install_path = str(parent)
            break
    if kind == "unknown" and "uv/tools" in install_path:
        kind = "uv_tool"
    if not sha:
        sha = "unknown"
    return {
        "source_sha": sha,
        "install_kind": kind,
        "install_path": install_path,
    }


def format_provenance_line(
    client: Mapping[str, Any],
    server: Optional[Mapping[str, Any]] = None,
    *,
    fallback_local: bool = False,
) -> str:
    """One stderr line naming client (and optional server) fingerprints."""

    def _fmt(label: str, blob: Mapping[str, Any]) -> str:
        sha = blob.get("source_sha") or "unknown"
        kind = blob.get("install_kind") or "unknown"
        path = blob.get("install_path") or "unknown"
        return f"{label} sha={sha} kind={kind} path={path}"

    parts = [_fmt("client", client)]
    if server:
        parts.append(_fmt("server", server))
    if fallback_local:
        parts.append("fallback=local")
    return "yoke-provenance " + " ".join(parts)


__all__ = [
    "PROVENANCE_KEYS",
    "collect_execution_provenance",
    "format_provenance_line",
]
