"""Candidate-string extraction for the stale-string audit gate.

Owns the helpers that turn an item spec/body and the live git diff into
the set of "old" user-visible strings that should no longer appear in
test fixtures:

* ``is_text_sensitive_item(item_id)`` — heuristic gate.
* ``extract_candidate_strings(item_id)`` — pull quoted strings from the
  spec/body.
* ``extract_candidate_strings_from_git_diff(search_root)`` — pull removed
  string literals from the working-tree diff.
* ``_collect_diff_strings(search_root)`` — collect added + removed
  literals across unstaged, staged, and ``main...HEAD`` diffs.
* ``_normalize_candidate_string(value)`` — central normalization /
  rejection rules for candidate strings.

Co-located here because all four helpers share the same regex patterns
and rejection logic; splitting them across modules would require
duplicating ``_normalize_candidate_string``.
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Optional

from yoke_core.domain._stale_string_audit_constants import (
    FILE_LIKE_SUFFIXES,
    GENERIC_QUOTED_STRINGS,
    TEXT_SENSITIVE_KEYWORDS,
)
from yoke_core.domain.stale_string_audit_discover import _get_item_field


def is_text_sensitive_item(item_id: int) -> bool:
    """Heuristic gate for items that need stale-string enforcement."""
    title = _get_item_field(item_id, "title")
    spec = _get_item_field(item_id, "spec")
    body = spec or _get_item_field(item_id, "body")
    haystack = "\n".join(part for part in (title, body) if part).lower()
    return any(keyword in haystack for keyword in TEXT_SENSITIVE_KEYWORDS)


def extract_candidate_strings(item_id: int) -> List[str]:
    """Extract likely old user-visible strings from the item spec/body."""
    spec = _get_item_field(item_id, "spec")
    body = spec or _get_item_field(item_id, "body")
    if not body:
        return []

    candidates: List[str] = []
    patterns = (
        re.compile(r'"([^"\n]{2,120})"'),
        re.compile(r"`([^`\n]{2,120})`"),
    )
    for pattern in patterns:
        for match in pattern.finditer(body):
            candidate = _normalize_candidate_string(match.group(1))
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def extract_candidate_strings_from_git_diff(search_root: str) -> List[str]:
    """Extract removed string literals from the live git diff."""
    try:
        proc = subprocess.run(
            ["git", "-C", search_root, "diff", "--no-color", "--unified=0"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        return []

    candidates: List[str] = []
    patterns = (
        re.compile(r'"([^"\n]{2,120})"'),
        re.compile(r"`([^`\n]{2,120})`"),
    )
    for raw_line in proc.stdout.splitlines():
        if not raw_line.startswith("-") or raw_line.startswith("---"):
            continue
        line = raw_line[1:]
        for pattern in patterns:
            for match in pattern.finditer(line):
                candidate = _normalize_candidate_string(match.group(1))
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
    return candidates


def _collect_diff_strings(search_root: str) -> tuple[set, set]:
    """Collect added and removed string literals across all relevant git diffs.

    Combines three views so no added/removed string is missed:

    * ``git diff`` — unstaged working-tree changes
    * ``git diff --staged`` — staged index changes
    * ``git diff main...HEAD`` — branch commits since the main fork point

    Returns a ``(added, removed)`` pair of string sets. Errors from any single
    diff invocation are swallowed — an empty or missing branch is fine.
    """
    added: set = set()
    removed: set = set()
    patterns = (
        re.compile(r'"([^"\n]{2,120})"'),
        re.compile(r"`([^`\n]{2,120})`"),
        re.compile(r"'([^'\n]{2,120})'"),
    )
    diff_cmds = (
        ["git", "-C", search_root, "diff", "--no-color", "--unified=0"],
        ["git", "-C", search_root, "diff", "--staged", "--no-color", "--unified=0"],
        ["git", "-C", search_root, "diff", "main...HEAD",
         "--no-color", "--unified=0"],
    )

    for cmd in diff_cmds:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
        if proc.returncode not in (0, 1) or not proc.stdout.strip():
            continue
        for raw_line in proc.stdout.splitlines():
            if raw_line.startswith("+++") or raw_line.startswith("---"):
                continue
            if raw_line.startswith("+"):
                target = added
            elif raw_line.startswith("-"):
                target = removed
            else:
                continue
            line = raw_line[1:]
            for pattern in patterns:
                for match in pattern.finditer(line):
                    val = " ".join(match.group(1).split()).strip()
                    if val:
                        target.add(val)
    return added, removed


def _normalize_candidate_string(value: str) -> Optional[str]:
    candidate = " ".join(value.split()).strip()
    if len(candidate) < 3 or len(candidate) > 120:
        return None
    if candidate.startswith("YOK-") or candidate in GENERIC_QUOTED_STRINGS:
        return None
    if any(ch in candidate for ch in "{}[]"):
        return None
    lower = candidate.lower()
    if lower.startswith(("python3 ", "git ", "npm ", "npx ", "pnpm ", "yarn ")):
        return None
    if lower.startswith("--"):
        return None
    if any(lower.endswith(suffix) for suffix in FILE_LIKE_SUFFIXES):
        return None
    if "/" in candidate or "\\" in candidate:
        # Reject URL route path patterns entirely.
        # Strings like "/login", "/forgot-password" are structural route
        # references, not user-visible copy that needs audit tracking.
        if re.fullmatch(r"/[a-z0-9/_-]{1,80}", lower):
            return None
        # Non-route paths with slashes/backslashes are still rejected
        return None
    if "_" in candidate and " " not in candidate:
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9:.+-]*", candidate):
        if not (
            candidate.isupper()
            or (candidate[0].isupper() and candidate[1:].islower())
        ):
            return None
    if not re.search(r"[A-Za-z]", candidate):
        return None
    return candidate
