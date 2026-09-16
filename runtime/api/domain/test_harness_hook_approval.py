"""Cursor has no declared hook-approval gate; stale prompt teaching stays gone."""

from __future__ import annotations

import re
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

#: Teaching that Cursor has a hook-specific approval or reapproval prompt.
_STALE_CURSOR_HOOK_APPROVAL = re.compile(
    r"Cursor's hooks? approval prompt"
    r"|Cursor still shows an approval prompt"
    r"|Cursor's hook-approval"
    r"|Cursor's hook approval prompt",
    re.IGNORECASE,
)

_SCAN_ROOTS = (
    _REPO / "packages",
    _REPO / "docs",
    _REPO / "runtime",
    _REPO / ".agents",
    _REPO / "CURSOR.md",
    _REPO / "CODEX.md",
    _REPO / "AGENTS.md",
)


def _iter_teaching_files():
    for root in _SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".json"}:
                continue
            if "archive" in path.parts or "worktrees" in path.parts:
                continue
            if path.resolve() == _SELF:
                continue
            yield path


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


def test_mapping_absence_is_not_proof_of_no_trust_gate():
    bootstrap = (_REPO / "docs" / "harness-bootstrap.md").read_text(encoding="utf-8")
    assert "A harness absent from that mapping has no gate." not in bootstrap
    assert "no declared hook-specific approval requirement" in bootstrap
    assert "not proof there is no trust gate" in bootstrap


def test_stale_cursor_hook_approval_teaching_is_absent():
    hits: list[str] = []
    for path in _iter_teaching_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if _STALE_CURSOR_HOOK_APPROVAL.search(line):
                hits.append(f"{path.relative_to(_REPO)}:{index}:{line.strip()}")
    assert hits == [], (
        "stale Cursor hook-approval prompt teaching must not return:\n"
        + "\n".join(hits)
    )
