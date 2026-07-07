"""Audit summary builder for the stale-string audit gate.

Owns ``build_audit_summary(item_id, search_root)`` — the deterministic
summary that combines test-surface discovery, candidate-string
extraction (git diff first, spec/body fallback), and grep results into
a single verdict-bearing dict.
"""

from __future__ import annotations

from typing import Any, Dict, List

from yoke_core.domain.stale_string_audit_discover import discover_test_surfaces
from yoke_core.domain.stale_string_audit_extract import (
    _collect_diff_strings,
    _normalize_candidate_string,
    extract_candidate_strings,
    is_text_sensitive_item,
)
from yoke_core.domain.stale_string_audit_grep import grep_surfaces


def build_audit_summary(item_id: int, search_root: str) -> Dict[str, Any]:
    """Build the deterministic stale-string audit summary for an item.

    Candidate-string resolution is OLD-string-only:

    1. Prefer strings found on ``-`` lines of the combined git diffs —
       these are unambiguously the values being replaced away from.
    2. If no removals exist (e.g. preflight before any edit), fall back to
       quoted-literal extraction from the item spec, but filter out any
       candidate that also appears on a ``+`` line (those are new strings
       the agent intentionally placed — they must not be flagged as stale).
    """
    surface_info = discover_test_surfaces(item_id)
    text_sensitive = is_text_sensitive_item(item_id)

    added_strings, removed_strings = _collect_diff_strings(search_root)
    spec_candidates = extract_candidate_strings(item_id)

    candidate_strings: List[str] = []
    candidate_source = "none"

    if removed_strings:
        # Removed-but-not-readded — the real "old" set.
        old_only = removed_strings - added_strings
        for raw in sorted(old_only):
            normalized = _normalize_candidate_string(raw)
            if normalized and normalized not in candidate_strings:
                candidate_strings.append(normalized)
        if candidate_strings:
            candidate_source = "git_diff_removed"

    if not candidate_strings and spec_candidates:
        filtered = [s for s in spec_candidates if s not in added_strings]
        if filtered:
            candidate_strings = filtered
            candidate_source = "spec_body"

    summary: Dict[str, Any] = {
        **surface_info,
        "item_id": item_id,
        "text_sensitive": text_sensitive,
        "candidate_strings": candidate_strings,
        "candidate_source": candidate_source,
        "matches": [],
        "verdict": "not_text_sensitive",
    }

    if not text_sensitive:
        return summary

    had_any_source = bool(spec_candidates) or bool(removed_strings)
    if not had_any_source:
        summary["verdict"] = "missing_candidate_strings"
        return summary

    if not candidate_strings:
        # Everything extracted was a new string — nothing stale to check.
        summary["verdict"] = "clean"
        return summary

    matches = grep_surfaces(search_root, candidate_strings, surface_info["surfaces"])
    summary["matches"] = matches
    summary["verdict"] = "matches_found" if matches else "clean"
    return summary
