"""Installer-owned lines in the root ``.gitignore``.

Project install owns one line per local skill-discovery entry.
:func:`add_entry` and :func:`remove_entry`
are the shared mechanics: append a missing line, or drop exactly one owned
line while preserving every other byte.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    "add_entry",
    "planned_text",
    "remove_entry",
]
