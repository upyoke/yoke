"""Root ``.worktrees/`` ignore handling for project onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKTREES_IGNORE_ENTRY = ".worktrees/"


def report(repo_root: str | Path, *, apply: bool) -> dict[str, Any]:
    """Preview or apply the narrow root ``.gitignore`` worktree entry."""
    root = Path(repo_root).expanduser().resolve()
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = _has_worktrees_entry(text)
    payload: dict[str, Any] = {
        "path": str(path),
        "entry": WORKTREES_IGNORE_ENTRY,
        "present": present,
        "applied": False,
        "patch": [] if present else [f"+{WORKTREES_IGNORE_ENTRY}"],
        "status": "present" if present else "missing",
    }
    if present or not apply:
        return payload
    _append_entry(path, text)
    payload["present"] = True
    payload["applied"] = True
    payload["status"] = "written"
    return payload


def _has_worktrees_entry(text: str) -> bool:
    return any(line.strip() == WORKTREES_IGNORE_ENTRY for line in text.splitlines())


def _append_entry(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(prefix + WORKTREES_IGNORE_ENTRY + "\n", encoding="utf-8")


__all__ = ["WORKTREES_IGNORE_ENTRY", "report"]
