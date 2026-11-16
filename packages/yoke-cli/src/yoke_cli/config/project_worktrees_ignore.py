"""Installer-owned lines in the root ``.gitignore``.

Onboarding owns the ``.worktrees/`` line; project install also owns one line
per local skill-discovery entry. :func:`add_entry` and :func:`remove_entry`
are the shared mechanics: append a missing line, or drop exactly one owned
line while preserving every other byte.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKTREES_IGNORE_ENTRY = ".worktrees/"


def report(repo_root: str | Path, *, apply: bool) -> dict[str, Any]:
    """Preview or apply the narrow root ``.gitignore`` worktree entry."""
    root = Path(repo_root).expanduser().resolve()
    from yoke_cli.project_install.files import assert_resolved_targets_within

    assert_resolved_targets_within(
        root, [".gitignore"], context="root worktree-ignore mutation",
    )
    path = root / ".gitignore"
    existed = path.exists()
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = _has_entry(text, WORKTREES_IGNORE_ENTRY)
    payload: dict[str, Any] = {
        "path": str(path),
        "entry": WORKTREES_IGNORE_ENTRY,
        "present": present,
        "applied": False,
        "created_file": False,
        "patch": [] if present else [f"+{WORKTREES_IGNORE_ENTRY}"],
        "status": "present" if present else "missing",
    }
    if present or not apply:
        return payload
    _append_entry(path, text, WORKTREES_IGNORE_ENTRY)
    payload["present"] = True
    payload["applied"] = True
    payload["created_file"] = not existed
    payload["status"] = "written"
    return payload


def remove_owned_entry(
    repo_root: str | Path, *, created_file: bool,
) -> dict[str, Any]:
    """Remove one installer-owned worktree line, preserving all foreign text."""
    return remove_entry(repo_root, WORKTREES_IGNORE_ENTRY, created_file=created_file)


def add_entry(repo_root: str | Path, entry: str) -> bool:
    """Append *entry* to the root ``.gitignore`` when absent; return if written."""
    path = _gitignore(repo_root, "root ignore mutation")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _has_entry(text, entry):
        return False
    _append_entry(path, text, entry)
    return True


def planned_text(text: str, entry: str) -> str:
    """Return root ``.gitignore`` *text* as :func:`add_entry` would leave it."""
    if _has_entry(text, entry):
        return text
    return _with_entry(text, entry)


def remove_entry(
    repo_root: str | Path, entry: str, *, created_file: bool = False,
) -> dict[str, Any]:
    """Remove one owned *entry* line, preserving all foreign text."""
    path = _gitignore(repo_root, "root ignore removal")
    if not path.is_file():
        return {"removed": False, "deleted_file": False}
    text = path.read_text(encoding="utf-8")
    kept = []
    removed = False
    for line in text.splitlines(keepends=True):
        if not removed and line.strip() == entry:
            removed = True
            continue
        kept.append(line)
    if not removed:
        return {"removed": False, "deleted_file": False}
    remainder = "".join(kept)
    if created_file and not remainder:
        path.unlink()
        return {"removed": True, "deleted_file": True}
    path.write_text(remainder, encoding="utf-8", newline="")
    return {"removed": True, "deleted_file": False}


def _gitignore(repo_root: str | Path, context: str) -> Path:
    root = Path(repo_root).expanduser().resolve()
    from yoke_cli.project_install.files import assert_resolved_targets_within

    assert_resolved_targets_within(root, [".gitignore"], context=context)
    return root / ".gitignore"


def _has_entry(text: str, entry: str) -> bool:
    return any(line.strip() == entry for line in text.splitlines())


def _with_entry(text: str, entry: str) -> str:
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + entry + "\n"


def _append_entry(path: Path, text: str, entry: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_with_entry(text, entry), encoding="utf-8", newline="")


__all__ = [
    "WORKTREES_IGNORE_ENTRY",
    "add_entry",
    "planned_text",
    "remove_entry",
    "remove_owned_entry",
    "report",
]
