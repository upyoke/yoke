"""Cursor has no declared hook-approval gate."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from yoke_contracts.harness_hook_approval import (
    CURSOR_HOOKS_DOC_RETRIEVED,
    CURSOR_HOOKS_DOC_URL,
    HARNESS_HOOK_APPROVAL,
    hook_approval,
    trust_teaching,
)
from yoke_core.domain.overview_harness_hook_health import (
    harness_targets,
    session_identities,
)


_SELF = Path(__file__).resolve()
_REPO = next(
    parent for parent in [_SELF, *_SELF.parents] if (parent / "pyproject.toml").exists()
)

def test_cursor_has_no_hook_approval_gate():
    assert "cursor" not in HARNESS_HOOK_APPROVAL
    assert hook_approval("cursor") is None
    assert trust_teaching("cursor") is None
    assert trust_teaching("codex") is not None
    assert "Codex's hook-trust prompt" in trust_teaching("codex")


def test_overview_does_not_name_a_cursor_hook_approval_surface():
    now = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    seen = now.isoformat()
    targets = {
        row["key"]: row
        for row in harness_targets(
            session_identities([("cursor", "cursor-desktop", 1, seen, None, seen)]),
            now=now,
        )
    }
    assert targets["cursor"]["trust_surface"] is None


def test_cursor_absence_cites_official_hooks_docs():
    module = (
        _REPO
        / "packages"
        / "yoke-contracts"
        / "src"
        / "yoke_contracts"
        / "harness_hook_approval.py"
    )
    text = module.read_text(encoding="utf-8")
    assert CURSOR_HOOKS_DOC_URL in text
    assert CURSOR_HOOKS_DOC_RETRIEVED in text
    assert "trusted workspace" in text
    assert "reapproval" in text or "re-approval" in text
    assert "declared hook-specific approval" in text
    assert "absent for the same reason Claude is" not in text
    assert "there is no machine-readable" not in text
