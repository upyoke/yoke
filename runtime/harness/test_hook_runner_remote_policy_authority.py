"""Remote-policy authority boundary coverage."""

from __future__ import annotations

from runtime.harness.hook_runner.remote_policy import LOCAL_STATE_POLICIES


def test_db_backed_authority_guards_stay_server_side() -> None:
    """DB-backed guardrails are server-safe in the relay split.

    The project hook client must not grow a direct DB cache just to make
    claim/path/session authority decisions; those policies run under
    ``POST /v1/hooks/evaluate`` where the control-plane DB is available.
    """
    db_authority_guards = {
        "yoke_core.domain.lint_main_commit",
        "yoke_core.domain.lint_claim_ownership_mutations",
        "yoke_core.domain.lint_session_cwd",
        "yoke_core.domain.path_claim_bash_guard",
        "yoke_core.domain.path_claim_pre_edit_guard",
        "runtime.harness.hook_helpers_heartbeat",
        "yoke_core.domain.observe_pre",
        "yoke_core.domain.observe",
    }

    assert db_authority_guards.isdisjoint(LOCAL_STATE_POLICIES)
