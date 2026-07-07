"""Doc-drift assertion: AGENTS.md and CLAUDE.md carry identical
Bash-rule wording.

Today CLAUDE.md is a symlink to AGENTS.md, so identity is structural — the
symlink-existence assertion is the live invariant. The rule-content assertions
remain valid even if a future operator replaces the symlink with a real
duplicate file: the diff still has to be empty across the named anchors.

Per task 12 AC-11: both files must reference "Bash tool calls" (no
``Subagent`` qualifier).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
AGENTS_MD = REPO / "AGENTS.md"
CLAUDE_MD = REPO / "CLAUDE.md"


def test_claude_md_is_symlink_to_agents_md():
    """Structural identity: CLAUDE.md → AGENTS.md."""
    assert CLAUDE_MD.is_symlink(), (
        "CLAUDE.md must be a symlink to AGENTS.md so the two files cannot "
        "drift. If you are intentionally replacing the symlink with a real "
        "duplicate file, update this test to diff the rule bodies instead."
    )
    target = CLAUDE_MD.readlink() if hasattr(CLAUDE_MD, "readlink") else Path(
        Path.readlink(CLAUDE_MD)  # type: ignore[arg-type]
    )
    assert target.name == "AGENTS.md", (
        f"CLAUDE.md symlink target must be AGENTS.md; got {target}"
    )


def test_agents_md_uses_bash_tool_calls_phrasing():
    """AC-11: ``Subagent Bash calls`` retired in favor of ``Bash tool calls``."""
    text = AGENTS_MD.read_text()
    assert "Subagent Bash calls" not in text, (
        "AGENTS.md still carries the legacy 'Subagent Bash calls' rule heading; "
        "rewrite as 'Bash tool calls' per task 12 AC-11."
    )
    assert "Bash tool calls" in text, (
        "AGENTS.md must reference the 'Bash tool calls' rule heading."
    )


def test_claude_md_resolves_to_agents_md_content():
    """Reading CLAUDE.md must yield the AGENTS.md content (via symlink)."""
    assert CLAUDE_MD.read_text() == AGENTS_MD.read_text(), (
        "CLAUDE.md and AGENTS.md must carry identical text. "
        "If CLAUDE.md is a symlink (default), this is structural; if it has "
        "been replaced with a real file, ensure it stays in sync with AGENTS.md."
    )
