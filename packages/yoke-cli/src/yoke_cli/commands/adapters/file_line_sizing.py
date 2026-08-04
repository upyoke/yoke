"""Client-local authored-file sizing for path-selection surfaces."""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any


def _repo_root() -> pathlib.Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return pathlib.Path(result.stdout.strip()).resolve()


def survey_path_sizes(paths: list[str]) -> list[dict[str, Any]]:
    """Describe current line pressure for every surveyed project path."""
    try:
        from yoke_harness.git_hooks import file_line_check
    except ImportError as exc:
        raise RuntimeError(
            "Dash survey sizing requires yoke-harness; install/repair the "
            f"product helper package ({exc})."
        ) from exc
    root = _repo_root()
    if root is None:
        raise RuntimeError("Dash survey sizing requires a local git checkout.")
    policy = file_line_check.resolved_policy(root)
    results: list[dict[str, Any]] = []
    for raw_path in paths:
        path = raw_path.removeprefix("./")
        classification = file_line_check.classify_path(path, repo_root=root)
        count = file_line_check.line_count_file(root / path)
        results.append({
            "path": path,
            "current_line_count": count,
            "remaining_headroom": policy.limit - count,
            "at_or_over_limit": count >= policy.limit,
            "limit": policy.limit,
            "classification": classification.value,
        })
    return results


__all__ = ["survey_path_sizes"]
