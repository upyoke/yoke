"""Regression: canonical agent prompt bodies must not teach worktree-as-cwd.

This captures the failure mode where the Engineer prompt instructed agents to
``cd {worktree-path}`` and then run bare ``git status --porcelain``. Under
Claude Code, ``cd`` does not persist across Bash tool invocations and the
workspace-cwd-match lint correctly blocks writer-class commands invoked from a
non-worktree cwd. Agents looped on the blocked pattern instead of converging on
the anchored shapes (``git -C {worktree-path}`` / ``pytest --rootdir
{worktree-path}``).

The test bans the literal anti-pattern ``cd {worktree-path}`` only in the
top-level canonical agent bodies under ``runtime/agents/*.md``. It does not
recurse into ``runtime/agents/<role>/*.md`` fixture references such as
``tester/regression-detection.md``.
"""
from __future__ import annotations

from pathlib import Path

ANTI_PATTERN = "cd {worktree-path}"
ANCHOR_PATTERNS = (
    "git -C {worktree-path} branch --show-current",
    "git -C {worktree-path} status --porcelain",
)


def _repo_root() -> Path:
    # runtime/api/domain/this_file.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _hits(*paths: Path) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in paths:
        if not path.is_file():
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ANTI_PATTERN in line:
                out.append((str(path), lineno))
    return out


def test_top_level_canonical_agent_bodies_avoid_worktree_cd_anti_pattern() -> None:
    """``cd {worktree-path}`` is absent from ``runtime/agents/*.md``."""
    bodies = sorted((_repo_root() / "runtime" / "agents").glob("*.md"))
    assert bodies, "expected runtime/agents/*.md to contain canonical agent bodies"

    hits = _hits(*bodies)
    assert hits == [], (
        f"canonical agent body teaches the worktree-as-cwd anti-pattern "
        f"{ANTI_PATTERN!r}: {hits!r}. Use anchored shapes instead "
        "(`git -C {worktree-path}`, `pytest --rootdir {worktree-path}`)."
    )


def test_engineer_prompt_teaches_anchored_git_shapes() -> None:
    """The canonical Engineer body teaches the lint-compatible git anchors."""
    engineer = _repo_root() / "runtime" / "agents" / "engineer.md"
    text = engineer.read_text(encoding="utf-8")

    for pattern in ANCHOR_PATTERNS:
        assert pattern in text


def test_rendered_claude_engineer_adapter_avoids_worktree_cd_anti_pattern() -> None:
    """The rendered Claude Engineer adapter inherits the anchored shapes."""
    rendered = (
        _repo_root()
        / "runtime"
        / "harness"
        / "claude"
        / "agents"
        / "yoke-engineer.md"
    )
    if not rendered.is_file():
        # Fresh checkout where renderer has not run yet — the upstream canonical
        # body is the authority, asserted above. The renderer test suite covers
        # the render path itself.
        return

    hits = _hits(rendered)
    assert hits == [], (
        f"rendered Claude Engineer adapter still teaches the worktree-as-cwd "
        f"anti-pattern {ANTI_PATTERN!r}: {hits!r}. Re-run "
        "`python3 -m yoke_core.domain.agents_render render` after editing "
        "the canonical body at runtime/agents/engineer.md."
    )

    text = rendered.read_text(encoding="utf-8")
    for pattern in ANCHOR_PATTERNS:
        assert pattern in text
