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


def extract_file_budget_paths_set(spec_text: str) -> Set[str]:
    """Set-shaped convenience for callers that compare against claim sets."""
    return set(extract_file_budget_paths(spec_text))


__all__ = [
    "extract_file_budget_paths",
    "extract_file_budget_paths_set",
    "is_path_token",
]
