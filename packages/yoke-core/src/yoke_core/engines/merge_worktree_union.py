"""Union-merge an additive conflict's three stages, and judge the result.

``git merge-file --union`` keeps every line from both sides. That is the right
answer for an append-oriented list and the wrong one for a structured file,
where both sides adding the same key yields a document with the key twice.

Three things can be wrong with a union result, and all of them are decided
here rather than at resolution time. A conflict whose union is unsafe must be
classified as needing agent judgement in the first place — the trial merge
reports that classification, and a check that only ran later would let the
trial pass and the real merge fail with nothing useful to say.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_core.domain.project_scratch_dir import scratch_subdir
from yoke_core.domain.structured_file_validation import structured_document_error

CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


@dataclass(frozen=True)
class UnionMerge:
    """One conflict's three stages and the union of them."""

    base: str
    ours: str
    theirs: str
    text: str


def compute_union_merge(filepath: str, cwd: str, run_git) -> Optional[UnionMerge]:
    """Union-merge *filepath*'s conflict stages, or ``None`` if unreadable."""
    base = run_git(["show", f":1:{filepath}"], cwd=cwd, capture=True)
    ours = run_git(["show", f":2:{filepath}"], cwd=cwd, capture=True)
    theirs = run_git(["show", f":3:{filepath}"], cwd=cwd, capture=True)

    if any(r.returncode != 0 for r in (base, ours, theirs)):
        return None

    with scratch_subdir(prefix="merge-additive") as tmpdir:
        base_path = os.path.join(tmpdir, "base")
        ours_path = os.path.join(tmpdir, "ours")
        theirs_path = os.path.join(tmpdir, "theirs")
        Path(base_path).write_text(base.stdout)
        Path(ours_path).write_text(ours.stdout)
        Path(theirs_path).write_text(theirs.stdout)

        # git merge-file --union modifies ours_path in-place
        subprocess.run(
            ["git", "merge-file", "--union", ours_path, base_path, theirs_path],
            capture_output=True,
            text=True,
        )
        return UnionMerge(
            base=base.stdout,
            ours=ours.stdout,
            theirs=theirs.stdout,
            text=Path(ours_path).read_text(),
        )


def union_rejection(filepath: str, union: UnionMerge) -> Optional[str]:
    """Return why this union result must not be committed, or ``None``.

    Ordered cheapest first, and each one is a different way for a union to be
    wrong: it did not actually resolve, it dropped a side's work, or it
    produced text the file's own format does not accept.
    """
    for marker in CONFLICT_MARKERS:
        if marker in union.text:
            return "conflict markers remain"

    base_lines = set(union.base.splitlines())
    for source, label in ((union.ours, "ours"), (union.theirs, "theirs")):
        for line in source.splitlines():
            if line.strip() and line not in base_lines:
                if line not in union.text:
                    return f"content from {label} lost"

    invalid = structured_document_error(filepath, union.text)
    if invalid is not None:
        return f"union is not a valid document for this format: {invalid}"

    return None


def union_is_safe(filepath: str, cwd: str, run_git) -> bool:
    """Whether *filepath*'s conflict can be resolved by union merge at all."""
    union = compute_union_merge(filepath, cwd, run_git)
    if union is None:
        return False
    return union_rejection(filepath, union) is None


__all__ = [
    "CONFLICT_MARKERS",
    "UnionMerge",
    "compute_union_merge",
    "union_is_safe",
    "union_rejection",
]
