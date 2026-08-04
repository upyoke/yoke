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
    "packages/yoke-core/src/yoke_core/domain/_test_check_path_claim_helpers.py": {
        "count": 1,
        "reason": "branch_name_convention",
        "note": "synthetic worktree branch label in path-claim test helper",
    },
    "packages/yoke-core/src/yoke_core/domain/agent_stop_chains.py": {
        "count": 2,
        "reason": "branch_name_convention",
        "note": "worktree dirname token recognition and commit label from basename",
    },
    "packages/yoke-core/src/yoke_core/domain/backlog_queries.py": {
        "count": 3,
        "reason": "parsed_back_to_internal_id",
        "note": "public-ref parse and next-id allocation before project prefix is known",
    },
    "packages/yoke-core/src/yoke_core/domain/check_claim_boundary_audit.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "normalize audit correlation token to bare item id",
    },
    "packages/yoke-core/src/yoke_core/domain/check_claim_boundary_audit_correlation.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "normalize correlation token to bare item id",
    },
    "packages/yoke-core/src/yoke_core/domain/claim_chain_state.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "strip public prefix from epic token before int cast",
    },
    "packages/yoke-core/src/yoke_core/domain/deploy_pipeline_gates.py": {
        "count": 2,
        "reason": "commit_grep_token",
        "note": "commit-message grep keeps legacy internal-id token beside rendered ref",
    },
    "packages/yoke-core/src/yoke_core/domain/discovery_scan.py": {
        "count": 1,
        "reason": "scratch_path_convention",
        "note": "stable /tmp discovery-scan filename keyed by normalized item number",
    },
    "packages/yoke-core/src/yoke_core/domain/ephemeral_environment_item_binding.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "stop query matches historical YOK-{internal_id} environment labels",
    },
    "packages/yoke-core/src/yoke_core/domain/epic_task_sync.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "normalize epic ref token before numeric compare",
    },
    "packages/yoke-core/src/yoke_core/domain/handlers/shepherd_verdict_writes.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "shepherd_verdicts.item column stores legacy YOK-{items.id} keys",
    },
    "packages/yoke-core/src/yoke_core/domain/item_execution_status_helpers.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "detect whether operator token already carries a public prefix",
    },
    "packages/yoke-core/src/yoke_core/domain/item_status_transitions.py": {
        "count": 2,
        "reason": "parsed_back_to_internal_id",
        "note": "accept public-ref or bare numeric tokens at transition boundary",
    },
    "packages/yoke-core/src/yoke_core/domain/item_test_results_classify.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "strip prefix from classifier input before numeric parse",
    },
    "packages/yoke-core/src/yoke_core/domain/item_worktree_resolution.py": {
        "count": 1,
        "reason": "doc_comment_only",
        "note": "documents legacy YOK-{internal_id} worktree naming scheme",
    },
    "packages/yoke-core/src/yoke_core/domain/lint_claim_ownership_denials.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "match pre-render claim-work command summaries that used internal-id token",
    },
    "packages/yoke-core/src/yoke_core/domain/lint_shell_quoted_function_payload.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "skip item-ref-shaped argv tokens when scanning shell payloads",
    },
    "packages/yoke-core/src/yoke_core/domain/lint_shell_quoted_function_payload_messages.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "recognize item-ref argv tokens in denial message heuristics",
    },
    "packages/yoke-core/src/yoke_core/domain/lint_worktree_path_invariants.py": {
        "count": 2,
        "reason": "scratch_path_convention",
        "note": "legacy worktree directory basename under .worktrees/",
    },
    "packages/yoke-core/src/yoke_core/domain/observe_db_reads.py": {
        "count": 1,
        "reason": "doc_comment_only",
        "note": "documents dual public-ref and legacy resolver schemes",
    },
    "packages/yoke-core/src/yoke_core/domain/path_claims_dispatch_io.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "_YOKE_ITEM_PREFIX parsing constant for dispatch payloads",
    },
    "packages/yoke-core/src/yoke_core/domain/project_scratch_dir.py": {
        "count": 2,
        "reason": "scratch_path_convention",
        "note": "per-dispatch scratch subtree uses stable YOK-{internal_id} segment",
    },
    "packages/yoke-core/src/yoke_core/domain/render_body.py": {
        "count": 3,
        "reason": "legacy_key_lookup",
        "note": "shepherd_verdicts and related tables keyed by legacy YOK-{items.id}",
    },
    "packages/yoke-core/src/yoke_core/domain/sessions_offer_revalidation.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "strip public prefix before session-offer numeric lookup",
    },
    "packages/yoke-core/src/yoke_core/domain/sessions_queries_base.py": {
        "count": 3,
        "reason": "parsed_back_to_internal_id",
        "note": "normalize session query tokens to internal item ids",
    },
    "packages/yoke-core/src/yoke_core/domain/shepherd_gate.py": {
        "count": 2,
        "reason": "legacy_key_lookup",
        "note": "verdict lookup key remains legacy YOK-{items.id} storage shape",
    },
    "packages/yoke-core/src/yoke_core/domain/stale_string_audit_extract.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "filter quoted strings that look like item refs during audit extract",
    },
    "packages/yoke-core/src/yoke_core/domain/strategize_carry_cli.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "detect carry-cli argv tokens that already include a public prefix",
    },
    "packages/yoke-core/src/yoke_core/domain/worktree_lane_plan.py": {
        "count": 1,
        "reason": "doc_comment_only",
        "note": "documents fallback when public sequence cannot be read",
    },
    "packages/yoke-core/src/yoke_core/domain/worktree_preflight.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "strip known worktree branch prefixes before numeric parse",
    },
    "packages/yoke-core/src/yoke_core/domain/worktree_preflight_steps.py": {
        "count": 2,
        "reason": "doc_comment_only",
        "note": "documents dual public-ref and legacy worktree naming schemes",
    },
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_meta_lifecycle.py": {
        "count": 2,
        "reason": "legacy_key_lookup",
        "note": "HC remediation SQL examples use historical YOK-||i.id join shape",
    },
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_meta_runs.py": {
        "count": 1,
        "reason": "token_recognition",
        "note": "grep audit skips lines that already cite a public ref token",
    },
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_worktrees_branches.py": {
        "count": 1,
        "reason": "doc_comment_only",
        "note": "documents legacy branch naming beside public refs",
    },
    "packages/yoke-core/src/yoke_core/engines/done_transition_cleanup.py": {
        "count": 2,
        "reason": "branch_name_convention",
        "note": "trial branch glob and comment on legacy naming fallback",
    },
    "packages/yoke-core/src/yoke_core/engines/done_transition_merge_ops.py": {
        "count": 1,
        "reason": "doc_comment_only",
        "note": "documents branch resolution rather than inline ref construction",
    },
    "packages/yoke-core/src/yoke_core/engines/done_transition_preconditions.py": {
        "count": 1,
        "reason": "legacy_key_lookup",
        "note": "shepherd_verdicts row lookup uses legacy item key column value",
    },
    "packages/yoke-core/src/yoke_core/engines/done_transition_runtime.py": {
        "count": 1,
        "reason": "parsed_back_to_internal_id",
        "note": "accept public-ref tokens at done-transition runtime boundary",
    },
    "runtime/api/domain/qa_gates_reviewed_impl_test_support.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_ITEM_REF constant for QA gate fixtures",
    },
    "runtime/api/domain/qa_plan_execution_test_support.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_ITEM_REF constant for QA plan fixtures",
    },
    "runtime/api/epic_cascade_dispatch_test_support.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_ITEM_REF constant for epic cascade fixtures",
    },
    "runtime/api/epic_full_test_support.py": {
        "count": 1,
        "reason": "test_fixture_path",
        "note": "synthetic TEST_EPIC_REF constant for epic integration fixtures",
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
