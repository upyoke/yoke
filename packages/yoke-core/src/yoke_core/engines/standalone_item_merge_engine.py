"""Adapter from recorded standalone identity to the generic merge engine."""

from __future__ import annotations

import io
import sys


def run(
    *,
    item_id: int,
    repo_root: str,
    branch: str,
    source_sha: str,
    target: str,
    local_merge: bool,
) -> tuple[int, str]:
    """Run the engine while keeping lane name and merge source distinct."""
    from yoke_core.engines.merge_worktree import MergeArgs, run as merge_run

    captured = io.StringIO()
    saved_stdout = sys.stdout

    class _Tee:
        def write(self, text: str) -> int:
            saved_stdout.write(text)
            captured.write(text)
            return len(text)

        def flush(self) -> None:
            saved_stdout.flush()

    sys.stdout = _Tee()
    try:
        exit_code = merge_run(
            MergeArgs(
                branch=branch,
                source_sha=source_sha,
                target=target,
                item_id=item_id,
                expected_repo_root=repo_root,
                local_merge=local_merge,
                standalone=True,
            )
        )
    finally:
        sys.stdout = saved_stdout
    return exit_code, captured.getvalue()


__all__ = ["run"]
