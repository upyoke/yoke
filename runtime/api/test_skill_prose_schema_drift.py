"""Regression test: skill prose and docs must not teach confabulated columns.

the cleanup swept four classes of confabulated column references out of the
conduct/idea/do/refine skill prose plus the harness-substrate / commands
docs. This test is the structural backstop that catches any future drift
back in. Each test grounds against a small fixed file-set scope; widen
the scope via a follow-up ticket, not opportunistically here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_md(roots: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        out.extend(sorted(p for p in root.rglob("*.md") if p.is_file()))
    return out


def _hits(pattern: re.Pattern[str], paths: Iterable[Path]) -> List[Tuple[Path, int, str]]:
    found: List[Tuple[Path, int, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                found.append((path, lineno, line.rstrip()))
    return found


def _assert_no_hits(label: str, hits: List[Tuple[Path, int, str]]) -> None:
    if not hits:
        return
    rendered = "\n".join(
        f"  {p.relative_to(REPO_ROOT)}:{n}: {line}" for p, n, line in hits
    )
    raise AssertionError(f"{label} — {len(hits)} hit(s):\n{rendered}")


def test_no_items_worktree_path_in_skills_or_docs() -> None:
    """AC-1: items.worktree_path is not a real column; absolute path is composed."""
    paths = _iter_md([REPO_ROOT / ".agents/skills", REPO_ROOT / "docs"])
    _assert_no_hits(
        "items.worktree_path leaked into skill/docs prose",
        _hits(re.compile(r"items\.worktree_path"), paths),
    )


def test_no_epic_tasks_depends_on_in_conduct() -> None:
    """AC-2 / AC-13: real column is `dependencies`, not `depends_on`."""
    paths = _iter_md([REPO_ROOT / ".agents/skills/yoke/conduct"])
    qualified = re.compile(r"epic_tasks\.depends_on|FROM epic_tasks.*depends_on")
    bare = re.compile(r"\bdepends_on\b")
    _assert_no_hits(
        "`depends_on` references in conduct prose",
        _hits(qualified, paths) + _hits(bare, paths),
    )


def test_no_epic_progress_notes_nonexistent_columns() -> None:
    """AC-3: epic_progress_notes has no note_seq / .source / .headline."""
    paths = _iter_md([REPO_ROOT / ".agents/skills/yoke"])
    pattern = re.compile(
        r"epic_progress_notes\.note_seq"
        r"|epic_progress_notes\.source\b"
        r"|epic_progress_notes\.headline"
    )
    _assert_no_hits("epic_progress_notes non-existent column references", _hits(pattern, paths))


def test_no_qa_requirements_nonexistent_columns() -> None:
    """AC-4: qa_requirements has no `required` / `satisfied_at` columns."""
    paths = _iter_md([REPO_ROOT / ".agents/skills/yoke"])
    pattern = re.compile(r"qa_requirements\.required\b|qa_requirements\.satisfied_at")
    _assert_no_hits("qa_requirements non-existent column references", _hits(pattern, paths))


def test_no_github_authh_targets_or_path_claim_targets_nonexistent_columns() -> None:
    """AC-11: real columns are path_targets.path_string and path_claim_targets.{claim_id,target_id}."""
    paths = _iter_md(
        [
            REPO_ROOT / ".agents/skills/yoke/idea",
            REPO_ROOT / ".agents/skills/yoke/refine",
            REPO_ROOT / "runtime/agents",
        ],
    )
    pattern = re.compile(
        r"path_targets\.path\b"
        r"|path_targets\.path_claim_id"
        r"|path_claim_targets\.path_claim_id"
        r"|path_claim_targets\.path_target_id"
    )
    _assert_no_hits("path_targets / path_claim_targets confabulated columns", _hits(pattern, paths))


def test_no_claim_state_flag_references() -> None:
    """AC-12: `--claim-state` is not a real flag; canonical flag is `--state`."""
    paths = _iter_md(
        [
            REPO_ROOT / ".agents/skills/yoke",
            REPO_ROOT / "runtime/agents",
            REPO_ROOT / "docs",
        ],
    )
    _assert_no_hits(
        "`--claim-state` flag references (use --state)",
        _hits(re.compile(r"--claim-state\b"), paths),
    )
