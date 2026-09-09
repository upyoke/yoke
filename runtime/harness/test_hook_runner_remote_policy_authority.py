"""Remote-policy authority boundary coverage."""

from __future__ import annotations

from yoke_core.hooks.remote_policy import LOCAL_STATE_POLICIES as REMOTE_LOCAL_POLICIES
from yoke_harness.hooks import local_subset


def test_db_backed_authority_guards_stay_server_side() -> None:
    """DB-backed guardrails are server-safe in the relay split.

    The project hook client must not grow a direct DB cache just to make
    claim/path/session authority decisions; those policies run under
    ``POST /v1/hooks/evaluate`` where the control-plane DB is available.
    """
    db_authority_guards = {
        "yoke_core.domain.lint_main_commit",
        "yoke_core.domain.lint_workspace_cwd_match",
        "yoke_core.domain.lint_claim_ownership_mutations",
        "yoke_core.domain.lint_session_cwd",
        "yoke_core.domain.lint_lane_main_write",
        "yoke_core.domain.path_claim_bash_guard",
        "yoke_core.domain.path_claim_pre_edit_guard",
        "yoke_core.hooks.heartbeat",
        "yoke_core.domain.observe_pre",
        "yoke_core.domain.observe",
    }

    assert db_authority_guards.isdisjoint(REMOTE_LOCAL_POLICIES)


def test_unmatched_path_glob_has_client_owned_remote_split() -> None:
    module_id = "yoke_core.domain.lint_unmatched_path_glob"

    assert module_id in REMOTE_LOCAL_POLICIES
    assert module_id in local_subset.LOCAL_STATE_POLICIES
    assert module_id in local_subset._POLICY_EVALUATORS
