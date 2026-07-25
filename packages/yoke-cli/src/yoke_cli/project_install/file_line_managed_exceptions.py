"""Exempt the rules files the installer writes from the line limit.

``yoke project install`` writes a managed block into a project's Markdown
rules files, and it installs the pre-merge gate that enforces the
authored-file line limit. The managed block is one contiguous region well
past that limit — currently the shipped doctrine plus the generated
``main_agent`` packet — so without this the install hands a project a gate
that refuses the install's own output, and the project's very first commit
fails on files it does not own and cannot split.

The exemption is written into the project's own ``.yoke/project.config``
rather than baked into the shipped policy, so the reason is visible where a
project owner looks for it and stays theirs to edit. Writes are additive and
idempotent: an entry already present is left alone, and nothing else in the
file is touched.

Scope is exactly the paths the bundle declares as managed-markdown targets.
The skills, agent adapters, and shipped reference docs the installer also
writes are classified as installer-rendered by path shape in the shared
policy and need no per-project entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from yoke_contracts.project_contract.file_line_policy import (
    FILE_LINE_EXCEPTION_KEY,
    PROJECT_CONFIG_REL,
)


_EXEMPTION_COMMENT = (
    "# Yoke-managed rules files. `yoke project install` writes one contiguous\n"
    "# managed block into each; a project cannot split a region it does not\n"
    "# own, so the authored-file line limit does not apply to these paths.\n"
    "# Content you add outside the managed markers is still yours to keep\n"
    "# readable — the exemption is about the block, not a licence to sprawl.\n"
)


def _existing_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _declared_entries(text: str) -> set[str]:
    """Return the exception globs the config already declares."""
    entries: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() == FILE_LINE_EXCEPTION_KEY:
            entries.add(value.strip())
    return entries


def ensure_managed_file_line_exceptions(
    repo_root: str | Path, managed_paths: Iterable[str],
) -> Dict[str, Any]:
    """Add a line-limit exception for each managed rules file.

    Returns an install-report fragment naming the paths added. Re-running is
    a no-op once every path is declared, so refresh does not accumulate
    duplicate entries or rewrite a config the project has since edited.
    """
    root = Path(repo_root)
    config = root / PROJECT_CONFIG_REL
    existing = _existing_text(config)
    declared = _declared_entries(existing)

    added: List[str] = [
        rel for rel in dict.fromkeys(managed_paths) if rel and rel not in declared
    ]
    if not added:
        return {"attempted": True, "status": "unchanged", "added": []}

    text = existing
    if text and not text.endswith("\n"):
        text += "\n"
    entries = "".join(f"{FILE_LINE_EXCEPTION_KEY}={rel}\n" for rel in added)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"{text}\n{_EXEMPTION_COMMENT}{entries}", encoding="utf-8")
    return {
        "attempted": True,
        "status": "ok",
        "added": added,
        "path": str(config),
    }


__all__ = ["ensure_managed_file_line_exceptions"]
