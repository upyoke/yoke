"""Which claimed paths do not exist yet, answered before any network call."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


UNMATERIALIZED_PATH_REFUSAL = (
    "these claimed paths exist in neither the committed tree nor the working "
    "tree, so the Canonical Path Registry cannot hold them: {paths}. Re-run "
    "with --allow-planned to claim them as future paths, or correct the "
    "spelling."
)


def unmaterialized_paths(
    paths: Sequence[str],
    *,
    repo_root: str | Path | None = None,
) -> list[str]:
    """Return claimed paths absent from both the committed and working trees.

    The registry is derived from committed tree state, so a path in neither
    the commit nor the checkout cannot be in it and a claim over it can only
    be refused. Answering that here costs one git call. Answering it at the
    server costs a whole-tree snapshot scan, a relay round trip, and — when
    the relay is retrying — minutes during which the command says nothing at
    all, which is how the refusal was first reported: as a hang.

    A probe that cannot run returns nothing. A check this cheap must never
    be the reason a legitimate claim is turned away.
    """
    wanted = [str(path).strip() for path in paths if str(path).strip()]
    if not wanted:
        return []
    root = _repo_root(repo_root)
    if root is None:
        return []
    committed = _committed_paths(root, wanted)
    return [
        path for path in wanted if path not in committed and not _present(root, path)
    ]


def _repo_root(repo_root: str | Path | None) -> Path | None:
    from yoke_cli.project_snapshot.scanner import (
        ProjectSnapshotScanError,
        resolve_repo_root,
    )

    try:
        return resolve_repo_root(repo_root)
    except (ProjectSnapshotScanError, OSError, ValueError):
        return None


def _present(root: Path, path: str) -> bool:
    candidate = root / path
    # A dangling symlink is still a path the operator created, so ask
    # whether the entry exists rather than whether it resolves.
    return candidate.is_symlink() or candidate.exists()


def _committed_paths(root: Path, paths: Sequence[str]) -> set[str]:
    """Ask git which of ``paths`` name an object in ``HEAD``.

    One batch call answers every path at once, so the probe stays flat in
    the number of claimed paths and independent of repository size.
    """
    query = "".join(f"HEAD:{path}\n" for path in paths).encode("utf-8")
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "--batch-check"],
            input=query,
            capture_output=True,
            check=False,
        )
    except OSError:
        return set(paths)
    if proc.returncode != 0:
        return set(paths)
    lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
    if len(lines) != len(paths):
        return set(paths)
    return {
        path
        for path, line in zip(paths, lines)
        if not line.rstrip().endswith("missing")
    }


__all__ = ["UNMATERIALIZED_PATH_REFUSAL", "unmaterialized_paths"]
