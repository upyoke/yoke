"""Name the producer history to inspect after a release consumer check fails."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *args], capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git returned no history")
    return result.stdout.strip()


def producer_failure_context(candidate: str, *, checkout: Path | None = None) -> str:
    """Report the full producer interval and item references without guessing a culprit.

    The bridge checks out the candidate with complete history and annotated
    release tags. Its parent's nearest release excludes the candidate's own
    tag when a promotion-time re-proof fails after tagging. Commit subjects
    supply item references; they are provenance to inspect, not a causal verdict.
    """
    root = checkout or Path.cwd()
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", candidate):
            raise ValueError("candidate must be a full commit")
        _git(root, "cat-file", "-e", f"{candidate}^{{commit}}")
        if _git(root, "rev-parse", "--is-shallow-repository") != "false":
            raise ValueError("producer history is shallow")
        try:
            tag = _git(
                root,
                "describe",
                "--first-parent",
                "--match",
                "v[0-9]*",
                "--abbrev=0",
                f"{candidate}^",
            )
        except ValueError:
            tag = ""
        if tag:
            baseline = _git(root, "rev-parse", f"{tag}^{{commit}}")
            interval = f"{baseline}..{candidate}"
            label = f"since prior annotated release {tag}"
            subjects = _git(root, "log", "--format=%s", interval)
        else:
            roots = _git(root, "rev-list", "--max-parents=0", candidate).splitlines()
            interval = f"repository roots {', '.join(roots)} through {candidate}"
            label = "no prior annotated release baseline"
            subjects = _git(root, "log", "--format=%s", candidate)
        refs = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]*-\d+\b", subjects)))
        items = (
            ", ".join(refs)
            if refs
            else "no item references in producer commit subjects"
        )
        return (
            f"Producer Yoke changes to inspect ({label}): {interval}. "
            f"Producer item references: {items}. Compare this producer range "
            "with the failing consumer job before assigning the fix; the range "
            "identifies candidate changes, not a proven single culprit."
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return (
            f"producer_attribution_unavailable for Yoke candidate {candidate}: {exc}. "
            "Restore the release candidate checkout with full history and annotated "
            "release tags (fetch-depth: 0), then retry the same release gate; "
            "do not infer a producer item from missing history."
        )
