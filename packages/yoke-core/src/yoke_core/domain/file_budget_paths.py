"""Shared File Budget path extractor.

Single owner of the File Budget path language, consumed by both
``idea_readiness_check`` and ``path_claim_spec_coverage_gate``. Closes
the divergence where extensionless project-local paths were claimable but invisible to
readiness consistency checks.

Rules (single source of truth):

- The section is delimited by ``## File Budget``. Parsing continues
  through any ``### subheading`` blocks and stops at the next level-2
  ``## `` heading.
- Only list items (``- ...``) are inspected. A list item may contain
  multiple backticked tokens.
- A backticked token is a path when:
    * it matches the safe-path regex ``[\\w./_-]+`` for its full length,
    * AND it contains ``/`` and does not end with ``/``,
    * OR it is a top-level dotfile (``.gitignore``, ``.prettierrc``),
    * OR it is a top-level ALLCAPS markdown filename
      (``AGENTS.md``, ``CLAUDE.md``, etc.).
    * OR it is a known top-level build/config filename
      (``pyproject.toml``, ``package.json``, etc.).
- Extensionless files such as ``.yoke/lint-config`` are accepted on equal
  footing with extensioned files.

Filtered out:
- Lowercase dotted identifiers (function ids, event names, module dotted
  paths) such as ``items.section.upsert`` or ``db_claim.amend`` unless they
  are explicit top-level build/config filenames. Operational references are
  never file paths; the explicit carve-out keeps the intent visible to the
  next consumer.
- Inline symbol tokens that lack ``/`` (``release_item_claim``).
- Directory tokens that end in ``/``.
- Shell fragments such as ``>/dev/null 2>&1 || true``.
- Heading text and non-list prose.

Returns paths in first-occurrence order, deduplicated.
"""

from __future__ import annotations

import re
from typing import List, Set

_FILE_BUDGET_HEADER = re.compile(r"^## File Budget\b")
_LEVEL2_HEADER = re.compile(r"^## ")
_LIST_ITEM = re.compile(r"^\s*-\s")
_BACKTICKED = re.compile(r"`([^`]+)`")
_SAFE_PATH = re.compile(r"^[\w./_-]+$")
_TOP_LEVEL_DOTFILE = re.compile(r"^\.[A-Za-z0-9][\w.-]*$")
_TOP_LEVEL_ALLCAPS_MD = re.compile(r"^[A-Z][A-Z0-9_]*\.md$")
_DOTTED_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+$")
_TOP_LEVEL_BUILD_CONFIG_FILES = frozenset({
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "ruff.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "tsconfig.json",
    "uv.lock",
    "vite.config.ts",
    "yarn.lock",
})
_NO_REPO_SCOPE = re.compile(
    r"^\s*(?:-\s*)?N/A\s+[—-]\s+(.+?)\s*$",
    re.IGNORECASE,
)
_UNRESOLVED_BUDGET_VALUES = frozenset({
    "none",
    "tbd",
    "todo",
    "unknown",
    "unresolved",
})
_UNRESOLVED_PROSE = re.compile(
    r"^\s*UNRESOLVED(\s+[—-].*)?\s*$",
    re.IGNORECASE,
)
_FILE_BUDGET_BLOCK = re.compile(
    r"^## File Budget\b.*?(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

UNRESOLVED_FILE_BUDGET_MARKER = (
    "UNRESOLVED — this work item creates/grows authored code but the "
    "file shape is not yet known. `/yoke refine` MUST resolve the "
    "expected implementation shape before this item advances past "
    "`refining-idea`."
)
UNRESOLVED_FILE_BUDGET_SECTION = (
    f"## File Budget\n\n{UNRESOLVED_FILE_BUDGET_MARKER}\n"
)


def is_path_token(candidate: str) -> bool:
    """Return ``True`` when ``candidate`` is a File Budget path token."""
    if not candidate:
        return False
    if not _SAFE_PATH.match(candidate):
        return False
    if candidate.endswith("/"):
        return False
    if "/" in candidate:
        return True
    if _TOP_LEVEL_DOTFILE.match(candidate):
        return True
    if candidate in _TOP_LEVEL_BUILD_CONFIG_FILES:
        return True
    if _DOTTED_IDENTIFIER.match(candidate):
        return False
    return bool(_TOP_LEVEL_ALLCAPS_MD.match(candidate))


def extract_file_budget_paths(spec_text: str) -> List[str]:
    """Pull file path tokens from the ``## File Budget`` section.

    Returns paths in first-occurrence order, deduplicated. ``### sub``
    headings inside the section are followed; the next ``## `` heading
    terminates parsing.
    """
    if not spec_text:
        return []
    in_section = False
    seen: Set[str] = set()
    paths: List[str] = []
    for line in spec_text.splitlines():
        stripped = line.strip()
        if _LEVEL2_HEADER.match(stripped):
            in_section = bool(_FILE_BUDGET_HEADER.match(stripped))
            continue
        if not in_section:
            continue
        if not _LIST_ITEM.match(line):
            continue
        for match in _BACKTICKED.finditer(line):
            candidate = match.group(1)
            if not is_path_token(candidate):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            paths.append(candidate)
    return paths


def extract_file_budget_section(spec_text: str) -> str | None:
    """Return the File Budget section body, or ``None`` when absent."""
    if not spec_text:
        return None
    in_section = False
    lines: list[str] = []
    for line in spec_text.splitlines():
        stripped = line.strip()
        if _LEVEL2_HEADER.match(stripped):
            if in_section:
                break
            in_section = bool(_FILE_BUDGET_HEADER.match(stripped))
            continue
        if in_section:
            lines.append(line)
    return "\n".join(lines).strip()


def has_resolved_file_budget(spec_text: str) -> bool:
    """Whether a section names paths or a reasoned no-repo-scope exception."""
    section = extract_file_budget_section(spec_text)
    if section is None:
        return False
    if extract_file_budget_paths(spec_text):
        return True
    for line in section.splitlines():
        match = _NO_REPO_SCOPE.match(line)
        if match and match.group(1).strip().casefold() not in _UNRESOLVED_BUDGET_VALUES:
            return True
    return False


def has_unresolved_file_budget(spec_text: str) -> bool:
    """Whether File Budget declares the documented UNRESOLVED deferral.

    Recognizes the idea-skill prose shape (``UNRESOLVED — …``) and the
    list form (``- N/A — unresolved`` / tbd / todo / unknown / none).
    Empty or missing sections are not unresolved deferrals. Resolved
    budgets return False.
    """
    if has_resolved_file_budget(spec_text):
        return False
    section = extract_file_budget_section(spec_text)
    if section is None:
        return False
    for line in section.splitlines():
        if _UNRESOLVED_PROSE.match(line):
            return True
        match = _NO_REPO_SCOPE.match(line)
        if match and match.group(1).strip().casefold() in _UNRESOLVED_BUDGET_VALUES:
            return True
    return False


def extract_file_budget_paths_set(spec_text: str) -> Set[str]:
    """Set-shaped convenience for callers that compare against claim sets."""
    return set(extract_file_budget_paths(spec_text))


def apply_unresolved_file_budget_marker(spec_text: str) -> str:
    """Insert the documented idea-status UNRESOLVED File Budget marker.

    Leaves resolved or already-unresolved budgets unchanged. Replaces an
    empty ``## File Budget`` section; otherwise appends the section.
    """
    text = spec_text or ""
    if has_unresolved_file_budget(text) or has_resolved_file_budget(text):
        return text
    if _FILE_BUDGET_BLOCK.search(text):
        return _FILE_BUDGET_BLOCK.sub(UNRESOLVED_FILE_BUDGET_SECTION, text, 1)
    prefix = text.rstrip()
    if prefix:
        return f"{prefix}\n\n{UNRESOLVED_FILE_BUDGET_SECTION}"
    return UNRESOLVED_FILE_BUDGET_SECTION


__all__ = [
    "UNRESOLVED_FILE_BUDGET_MARKER",
    "UNRESOLVED_FILE_BUDGET_SECTION",
    "apply_unresolved_file_budget_marker",
    "extract_file_budget_paths",
    "extract_file_budget_section",
    "extract_file_budget_paths_set",
    "has_resolved_file_budget",
    "has_unresolved_file_budget",
    "is_path_token",
]
