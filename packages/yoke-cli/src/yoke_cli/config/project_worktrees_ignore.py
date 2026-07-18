"""Root ``.worktrees/`` ignore handling for project onboarding."""

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
    present = _has_worktrees_entry(text)
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
    _append_entry(path, text)
    payload["present"] = True
    payload["applied"] = True
    payload["created_file"] = not existed
    payload["status"] = "written"
    return payload


def remove_owned_entry(
    repo_root: str | Path, *, created_file: bool,
) -> dict[str, Any]:
    """Remove one installer-owned worktree line, preserving all foreign text."""
    root = Path(repo_root).expanduser().resolve()
    from yoke_cli.project_install.files import assert_resolved_targets_within

    assert_resolved_targets_within(
        root, [".gitignore"], context="root worktree-ignore removal",
    )
    path = root / ".gitignore"
    if not path.is_file():
        return {"removed": False, "deleted_file": False}
    text = path.read_text(encoding="utf-8")
    kept = []
    removed = False
    for line in text.splitlines(keepends=True):
        if not removed and line.strip() == WORKTREES_IGNORE_ENTRY:
            removed = True
            continue
        kept.append(line)
    if not removed:
        return {"removed": False, "deleted_file": False}
    remainder = "".join(kept)
    if created_file and not remainder:
        path.unlink()
        return {"removed": True, "deleted_file": True}
    path.write_text(remainder, encoding="utf-8")
    return {"removed": True, "deleted_file": False}


def _has_worktrees_entry(text: str) -> bool:
    return any(line.strip() == WORKTREES_IGNORE_ENTRY for line in text.splitlines())


def _append_entry(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(prefix + WORKTREES_IGNORE_ENTRY + "\n", encoding="utf-8")


__all__ = ["WORKTREES_IGNORE_ENTRY", "remove_owned_entry", "report"]
