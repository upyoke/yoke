"""Remote-policy authority boundary coverage."""

from __future__ import annotations

from yoke_contracts.hook_runner.policy_home import CLIENT_POLICIES
from yoke_harness.hooks import local_subset


def test_db_backed_authority_guards_stay_server_side() -> None:
    """DB-backed guardrails are server-run in the relay split.

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
        "yoke_core.hooks.session_resume_block",
        "yoke_core.domain.observe_pre",
        "yoke_core.domain.observe",
    }

    assert db_authority_guards.isdisjoint(CLIENT_POLICIES)


def test_unmatched_path_glob_is_client_run() -> None:
    module_id = "yoke_core.domain.lint_unmatched_path_glob"

    assert module_id in CLIENT_POLICIES
    assert module_id in local_subset._POLICY_EVALUATORS
