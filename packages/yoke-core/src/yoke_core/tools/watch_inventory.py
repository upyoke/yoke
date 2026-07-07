"""Residue check for hand-authored Monitor filters and stale Monitor prose.

Finds live Yoke prompt and documentation surfaces that still teach
agents the wrong Monitor primitive shape for long-running commands.
Two anti-patterns are caught:

1. ``tail -f ... | grep --line-buffered ...`` — hand-authored progress
   filter taught as the preferred path. Once
   :mod:`yoke_core.tools.watch_pytest`,
   :mod:`yoke_core.tools.watch_merge`,
   :mod:`yoke_core.tools.watch_doctor`,
   :mod:`yoke_core.tools.watch_advance`,
   :mod:`yoke_core.tools.watch_lifecycle`, and
   :mod:`yoke_core.tools.watch_session_offer` exist, the canonical
   guidance is to call those wrappers; the hand-authored filter stays
   only as labelled fallback documentation.
2. ``permissive `tail -f``` (and variants) — prose teaching bare
   ``tail -f`` as if it were the Monitor primitive. Once
   :mod:`yoke_core.tools.watch_tail` exists, the canonical
   Monitor primitive is ``watch_tail``; bare ``tail -f`` orphans a child
   process and lacks the wrapper's auto-exit sentinel.

Usage::

    python3 -m yoke_core.tools.watch_inventory check   # exit 1 on findings
    python3 -m yoke_core.tools.watch_inventory list    # always exit 0

For class (1): a finding is reported when a line contains BOTH
``tail -f`` and ``grep --line-buffered`` and the surrounding context (5
lines before and after) does not contain any of ``fallback``,
``watch_pytest``, ``watch_merge``, ``watch_doctor``, ``watch_advance``,
``watch_lifecycle``, or ``watch_session_offer``.

For class (2): a finding is reported when a line matches the broken
phrasing ``permissive ... tail -f`` (with or without backticks around
``tail -f``). This phrase only appears when teaching Monitor wrong; no
fallback-context suppression applies.

The wrapper sources themselves are excluded from scanning so the
residue check does not flag its own example text.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Live surfaces the residue check scans. Repo-relative; resolved against
# the repo root at call time. Generated views and vendored trees are
# excluded by skipping files entirely.
SCAN_ROOTS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs",
    "runtime/agents",
    "runtime/harness/claude/rules",
    ".agents/skills",
)

# Files we never scan — including the wrapper implementations whose
# example output legitimately includes the hand-authored pattern.
EXCLUDE_PATHS: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/tools/watch_pytest.py",
    "packages/yoke-core/src/yoke_core/tools/watch_merge.py",
    "packages/yoke-core/src/yoke_core/tools/watch_doctor.py",
    "packages/yoke-core/src/yoke_core/tools/watch_advance.py",
    "packages/yoke-core/src/yoke_core/tools/watch_lifecycle.py",
    "packages/yoke-core/src/yoke_core/tools/watch_session_offer.py",
    "packages/yoke-core/src/yoke_core/tools/watch_inventory.py",
    "packages/yoke-core/src/yoke_core/tools/_watch_runner.py",
    "runtime/api/tools/test_watch_pytest.py",
    "runtime/api/tools/test_watch_merge.py",
    "runtime/api/tools/test_watch_doctor.py",
    "runtime/api/tools/test_watch_advance.py",
    "runtime/api/tools/test_watch_lifecycle.py",
    "runtime/api/tools/test_watch_session_offer.py",
    "runtime/api/tools/test_watch_inventory.py",
    "runtime/api/tools/test_watch_runner.py",
)

# Fallback-context tokens. If any appears within ``CONTEXT_RADIUS`` lines
# of a hand-authored-pattern hit, the hit is treated as labelled fallback
# documentation and is not flagged.
FALLBACK_TOKENS: tuple[str, ...] = (
    "fallback",
    "watch_pytest",
    "watch_merge",
    "watch_doctor",
    "watch_advance",
    "watch_lifecycle",
    "watch_session_offer",
)
CONTEXT_RADIUS = 5

HAND_AUTHORED_PATTERN = re.compile(r"tail -f .*grep --line-buffered")

# Class-2 pattern: prose teaching bare ``tail -f`` as the Monitor primitive.
# The phrase "permissive tail -f" (with or without backticks around
# ``tail -f``) is the unambiguous marker of the broken teaching — it does
# not appear in correct guidance because the canonical Monitor primitive
# (``watch_tail``) is not described as "permissive". No fallback-context
# suppression applies; if this phrase is in the surface, the surface is
# teaching the wrong primitive.
# STALE_MONITOR_PROSE_PATTERN is **retained as
# defense-in-depth**. The PreToolUse hook
# ``lint_long_command_polling.evaluate_duplicate_monitor`` now denies
# duplicate-Monitor invocations structurally at agent runtime, which
# covers the failure mode this lint was originally chartered against.
# The prose lint targets a different audience and a different
# lifecycle stage: it fires when docs / skills / prompts are AUTHORED
# with the stale "permissive ``tail -f``" framing, so a writer never
# ships text that would teach agents to ignore the wrapper. Removing
# the prose lint would silently allow drift back into authored
# surfaces; the structural deny would catch the runtime symptom but
# the doctrine surface would be wrong. The two surfaces are
# complementary — keep both.
STALE_MONITOR_PROSE_PATTERN = re.compile(r"permissive\s+`?\s*tail\s+-f")


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    line: str

    def render(self) -> str:
        return f"{self.path}:{self.line_number}: {self.line.rstrip()}"


def _iter_scan_files(repo_root: Path) -> list[Path]:
    """Return tracked-style file list under :data:`SCAN_ROOTS`."""
    files: list[Path] = []
    excluded = {repo_root / e for e in EXCLUDE_PATHS}
    for entry in SCAN_ROOTS:
        node = repo_root / entry
        if node.is_file():
            if node.resolve() not in {p.resolve() for p in excluded if p.exists()}:
                files.append(node)
            continue
        if not node.is_dir():
            continue
        for path in node.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(node).parts):
                # Skip dotfiles inside scanned dirs (e.g., editor caches),
                # but allow the .agents tree itself which is a top-level
                # SCAN_ROOTS entry already.
                continue
            if path.suffix.lower() not in {".md", ".py", ".json", ".sh"}:
                continue
            if path.resolve() in {p.resolve() for p in excluded if p.exists()}:
                continue
            files.append(path)
    return files


def _has_fallback_context(lines: list[str], idx: int) -> bool:
    start = max(0, idx - CONTEXT_RADIUS)
    end = min(len(lines), idx + CONTEXT_RADIUS + 1)
    window = " ".join(lines[start:end]).lower()
    return any(token in window for token in FALLBACK_TOKENS)


def find_residue(repo_root: Path) -> list[Finding]:
    """Walk live surfaces and collect Monitor anti-pattern hits.

    Catches two residue classes: unlabelled hand-authored
    ``tail -f ... | grep --line-buffered`` filters, and stale Monitor
    prose teaching ``permissive `tail -f``` as if it were the Monitor
    primitive (the correct primitive is ``watch_tail``).
    """
    findings: list[Finding] = []
    for path in _iter_scan_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if HAND_AUTHORED_PATTERN.search(line):
                if not _has_fallback_context(lines, idx):
                    findings.append(
                        Finding(path=path, line_number=idx + 1, line=line)
                    )
                continue
            if STALE_MONITOR_PROSE_PATTERN.search(line):
                findings.append(
                    Finding(path=path, line_number=idx + 1, line=line)
                )
    return findings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_inventory",
        description=(
            "Find live surfaces still teaching the hand-authored "
            "tail -f ... | grep --line-buffered pattern as the preferred "
            "path for long-running commands."
        ),
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("check", "list"),
        default="check",
        help="``check`` exits non-zero on findings; ``list`` always exits 0.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repo root (defaults to git toplevel of CWD).",
    )
    return parser.parse_args(list(argv))


def _resolve_repo_root(override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    ns = _parse_args(raw)
    repo_root = _resolve_repo_root(ns.repo_root)
    findings = find_residue(repo_root)
    if not findings:
        print("watch_inventory: no unlabelled hand-authored Monitor patterns found.")
        return 0
    print(
        f"watch_inventory: {len(findings)} unlabelled hand-authored "
        "Monitor pattern reference(s) found:"
    )
    for finding in findings:
        print(f"  {finding.render()}")
    return 1 if ns.mode == "check" else 0


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
