"""Cursor has no declared hook-approval gate; stale prompt teaching stays gone."""

from __future__ import annotations

import re
import subprocess
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
    _REPO / "docs/public/guides/cursor-harness.md",
    _REPO / "docs/public/guides/codex-harness.md",
    _REPO / "AGENTS.md",
)


def _iter_teaching_files(*, repo: Path = _REPO, roots: tuple[Path, ...] = _SCAN_ROOTS):
    """Scan tracked teaching, without entering transient wheel-build trees.

    Parallel packaging tests create and remove those trees while this check
    runs. The index names the source being verified and needs no tree walk.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "ls-files",
            "-z",
            "--",
            *(str(root.relative_to(repo)) for root in roots),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for relative in result.stdout.split("\0"):
        if not relative:
            continue
        path = repo / relative
        if not path.is_file() or path.suffix not in {".py", ".md", ".json"}:
            continue
        if "archive" in path.parts or "worktrees" in path.parts:
            continue
        if path.resolve() != _SELF:
            yield path


def test_teaching_scan_uses_tracked_sources_without_transient_build_trees(tmp_path):
    source = tmp_path / "packages" / "example" / "src" / "teaching.md"
    built = tmp_path / "packages" / "example" / "build" / "wheel" / "teaching.md"
    archived = tmp_path / "docs" / "archive" / "teaching.md"
    root_file = tmp_path / "AGENTS.md"
    for path in (source, built, archived, root_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("teaching\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "init"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "--",
            str(source),
            str(archived),
            str(root_file),
        ],
        check=True,
        capture_output=True,
    )

    files = set(
        _iter_teaching_files(
            repo=tmp_path,
            roots=(tmp_path / "packages", tmp_path / "docs", root_file),
        )
    )

    assert files == {source, root_file}


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
