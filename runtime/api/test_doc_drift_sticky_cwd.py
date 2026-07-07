r"""Smallest-viable doc-drift check: the AGENTS.md sticky-cwd doctrine
and the advance implementation skill prose must not contradict each
other.

The contradiction this catches (originally observed live on YOK-1742):

- AGENTS.md documents that Claude Code / Claude Desktop keep a
  sticky cwd between Bash tool calls, so a ``cd`` to an in-scope path
  silently persists across calls.
- The pre-fix advance skill prose said ``Do NOT rely on
  `cd <worktree>```. The agent followed both surfaces, did not ``cd``,
  and pytest collected from the main checkout instead of the worktree.

The assertions below pin three text-presence facts so the contradiction
cannot re-emerge silently:

1. AGENTS.md still teaches the sticky-cwd doctrine (text search on the
   canonical phrase that documents it).
2. The implementation skill body teaches the explicit
   ``cd "{WORKTREE_PATH}"`` Step 0 directive.
3. ``worktree.md`` no longer contains the obsoleted
   ``Do NOT rely on `cd <worktree>``` prose that contradicted (1) for
   sticky-cwd harnesses.

If a future authoring pass intentionally re-fences the cd directive to
specific harnesses, this test will fail loudly enough that the
reconciliation lands in the same commit — which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    # ``runtime/api/test_doc_drift_sticky_cwd.py`` → repo root is two
    # parents up. Tests run under either the main checkout or a worktree;
    # the relative resolution is identical in both.
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def repo_root() -> Path:
    return _repo_root()


def test_agents_md_carries_sticky_cwd_doctrine(repo_root: Path) -> None:
    """AGENTS.md still names the sticky-cwd surprise."""
    agents = repo_root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    # The canonical phrase that documents the sticky-cwd behaviour for
    # Claude Code / Claude Desktop.
    assert "sticky cwd" in text, (
        "AGENTS.md must continue to document the Claude Code / Desktop "
        "sticky cwd. If this surface is renamed, update both AGENTS.md "
        "and runtime/api/test_doc_drift_sticky_cwd.py in the same commit."
    )


def test_implementation_md_teaches_step_0_cd_directive(
    repo_root: Path,
) -> None:
    """The implementation re-anchor teaches an explicit Step 0 cd."""
    impl = (
        repo_root
        / ".agents"
        / "skills"
        / "yoke"
        / "advance"
        / "implementing"
        / "implementation.md"
    )
    text = impl.read_text(encoding="utf-8")
    # The Step 0 directive is the load-bearing reconciliation with
    # AGENTS.md's sticky-cwd block.
    assert '`cd "{WORKTREE_PATH}"`' in text, (
        "implementation.md must teach an explicit Step 0 `cd "
        '"{WORKTREE_PATH}"` directive at the top of the Implementation '
        "Re-Anchor block."
    )


def test_worktree_md_drops_contradictory_cd_prose(repo_root: Path) -> None:
    """The pre-fix ``Do NOT rely on `cd <worktree>``` line is gone."""
    wt = (
        repo_root / ".agents" / "skills" / "yoke" / "advance" / "worktree.md"
    )
    text = wt.read_text(encoding="utf-8")
    # The exact phrase that contradicted AGENTS.md for sticky-cwd
    # harnesses. If this re-appears (even as harness-fenced prose), it
    # should be inside a ``<!-- YOKE:HARNESS … -->`` block AND named
    # explicitly — at which point this assertion should be revised in
    # the same commit. Until then, the bare phrase is the regression
    # surface.
    forbidden = "Do NOT rely on `cd <worktree>`"
    assert forbidden not in text, (
        f"worktree.md must not contain the obsoleted prose "
        f"({forbidden!r}); it contradicts AGENTS.md's sticky-cwd "
        f"doctrine for Claude Code / Desktop. If the prose is "
        f"intentionally fenced for a non-sticky harness, update both "
        f"this test and the skill body in the same commit."
    )


def test_worktree_md_teaches_cd_canonical_first_action(
    repo_root: Path,
) -> None:
    """worktree.md now points at the Step 0 cd directive as canonical."""
    wt = (
        repo_root / ".agents" / "skills" / "yoke" / "advance" / "worktree.md"
    )
    text = wt.read_text(encoding="utf-8")
    # The replacement prose names the Step 0 directive so the contract
    # is single-sourced in implementation.md.
    assert "canonical first action" in text.lower(), (
        "worktree.md must teach the cd directive as the canonical first "
        "action and reference implementation.md's Step 0 directive."
    )


def test_engineer_body_drops_universal_cwd_loss_prose(
    repo_root: Path,
) -> None:
    """The canonical engineer body no longer asserts universal cwd loss.

    Pre-fix, ``runtime/agents/engineer.md`` carried the contradicted
    clause in two places (the Step 0 block and the Rules bullet),
    asserting that ``Bash `cd` does not survive a single tool
    invocation``. That claim contradicts AGENTS.md's sticky-cwd doctrine
    for Claude Code / Desktop main sessions; empirical probing under
    YOK-1807 also confirmed it should be harness-fenced to subagent
    dispatch contexts rather than asserted as a universal Claude Code
    fact.

    The forbidden substring below is the durable shared kernel of both
    pre-fix formulations (Step 0 wording "every Bash call starts fresh
    at the parent checkout's cwd" and Rules-bullet wording "under
    Claude Code"), so a single assertion catches both formulations and
    any future paraphrase that re-asserts the universal claim.
    """
    body = repo_root / "runtime" / "agents" / "engineer.md"
    text = body.read_text(encoding="utf-8")
    forbidden = "does not survive a single tool invocation"
    assert forbidden not in text, (
        f"runtime/agents/engineer.md must not contain the obsoleted prose "
        f"({forbidden!r}); it contradicts AGENTS.md's sticky-cwd doctrine "
        f"for Claude Code / Desktop main sessions. Subagent-dispatch cwd "
        f"behaviour is fenced via the harness-scoped wording introduced "
        f"under YOK-1807 — if a future authoring pass restates the "
        f"contradicted clause (even harness-fenced), revise this test "
        f"and the engineer body in the same commit."
    )


def test_harness_substrate_md_drops_universal_cwd_loss_prose(
    repo_root: Path,
) -> None:
    """The substrate doctrine doc no longer asserts universal cwd loss.

    Pre-fix, ``docs/harness-substrate.md`` carried the same contradicted
    clause the engineer body did — asserting that ``cd`` does not
    survive a single tool invocation in Claude Code generally. That
    claim contradicts AGENTS.md's sticky-cwd doctrine for the Claude
    Code / Desktop main session, and the empirical NOT_STICKY finding
    YOK-1807 recorded only applies to subagent dispatch contexts, not
    the main session.

    The rewritten substrate-doc prose harness-fences the cwd behaviour
    (sticky in the main session, revert-per-call in subagent dispatch
    contexts) and names the actual workspace lint
    (``runtime/api/domain/lint_session_cwd.py``) as the mechanism — work
    claims are the per-call authority signal, not cwd.

    The forbidden substring is pinned to the same kernel the engineer
    assertion uses, so the doctrine-level regression class is caught on
    both surfaces by symmetric assertions.
    """
    doc = repo_root / "docs" / "harness-substrate.md"
    text = doc.read_text(encoding="utf-8")
    forbidden = "does not survive a single tool invocation"
    assert forbidden not in text, (
        f"docs/harness-substrate.md must not contain the obsoleted prose "
        f"({forbidden!r}); it contradicts AGENTS.md's sticky-cwd doctrine "
        f"for the Claude Code / Desktop main session. Subagent-dispatch "
        f"cwd behaviour is fenced via the harness-scoped wording "
        f"introduced alongside the YOK-1807 engineer-body reconciliation "
        f"— if a future authoring pass restates the contradicted clause "
        f"(even harness-fenced), revise this test and the substrate doc "
        f"in the same commit."
    )
