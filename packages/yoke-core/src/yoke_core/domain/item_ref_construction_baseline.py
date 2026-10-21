"""Grandfathered ref-prefix-literal counts, keyed by repo-relative POSIX path.

HC-item-ref-construction is a ratchet: any literal item-ref prefix in a file
not listed here, or MORE occurrences than listed, fails the check. Each entry
records why the remaining literals are legitimate (parsing, legacy storage
keys, scratch paths, test fixtures, etc.). This map must shrink whenever a
listed source file changes: its maintainer owns reducing the matching
allowance. Empty => zero tolerance.
"""

from __future__ import annotations

BASELINE: dict[str, dict[str, object]] = {
    "packages/yoke-core/src/yoke_core/domain/item_landings_reconstruct.py": {
        "count": 3,
        "reason": "legacy_key_lookup",
        "note": "migration 0046 backfill reads historical YOK merge-commit subjects",
    },
    "packages/yoke-core/src/yoke_core/domain/migrations/0057_shepherd_public_refs.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "frozen migration rewrites stored YOK-{internal_id} shepherd keys",
    },
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_worktrees.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "Yoke-repo doctor check scans its own YOK worktree names",
    },
    "packages/yoke-core/src/yoke_core/domain/ephemeral_environment_item_binding.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "stop query matches historical YOK-{internal_id} environment labels",
    },
    "runtime/api/events_crud_test_fixtures.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "test fixture normalizes mixed-case prefix tokens to bare ids",
    },
    "runtime/api/merge_worktree_test_db.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_BRANCH label for merge-worktree DB fixtures",
    },
    "runtime/api/scheduler_test_fixtures.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "scheduler fixture detects prefixed item tokens in synthetic rows",
    },
    "runtime/api/update_status_environment_test_config.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_EPIC_REF constant for status environment fixtures",
    },
    "runtime/api/update_status_full_test_schema.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "fixture schema SQL strips YOK- prefix from stored text-ref column",
    },
}


def baseline_count(relpath: str) -> int:
    """Return the grandfathered occurrence count for *relpath*, or zero."""
    entry = BASELINE.get(relpath)
    if entry is None:
        return 0
    return int(entry["count"])


def baseline_counts() -> dict[str, int]:
    """Return the path → count map consumed by HC-item-ref-construction."""
    return {path: baseline_count(path) for path in BASELINE}


__all__ = ["BASELINE", "baseline_count", "baseline_counts"]
