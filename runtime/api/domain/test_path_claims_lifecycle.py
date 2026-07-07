"""Lifecycle (activate/release/cancel) tests for the path-claim domain.

Split from ``test_path_claims.py`` once the parent crossed the
file-line gate. Register-side coverage lives in
``test_path_claims.py``; classifier coverage in
``test_path_claims_overlap.py``. The shared ``conn`` fixture and
helpers come from ``_path_claims_test_helpers``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    SNAP,
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    ClaimNotFound,
    IllegalTransition,
    UpstreamNotReleased,
    activate,
    cancel,
    get_claim,
    register,
    release,
)
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.path_targets_planning import plan_path_target


class TestActivate:
    def test_activate_planned_acquires_lock(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "active"
        assert claim["base_commit_sha"] == SNAP
        assert claim["activated_at"] is not None

    def test_activate_idempotent(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        first_at = get_claim(conn, claim_id)["activated_at"]
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        assert get_claim(conn, claim_id)["activated_at"] == first_at

    def test_activate_rejects_terminal_states(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        cancel(conn, claim_id=claim_id, reason="scope-changed")
        with pytest.raises(IllegalTransition):
            activate(conn, claim_id=claim_id, base_commit_sha=SNAP)

    def test_activate_blocked_requires_released_upstream(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        downstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            upstream_claim_id=upstream,
        )
        with pytest.raises(UpstreamNotReleased):
            activate(
                conn,
                claim_id=downstream,
                base_commit_sha=SNAP,
                upstream_claim_id=upstream,
            )
        activate(conn, claim_id=upstream, base_commit_sha=SNAP)
        release(conn, claim_id=upstream, reason="merged-into-main")
        activate(
            conn,
            claim_id=downstream,
            base_commit_sha=SNAP,
            upstream_claim_id=upstream,
        )
        assert get_claim(conn, downstream)["state"] == "active"

    def test_activate_blocked_rejects_wrong_released_upstream(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        other_target = seed_target(conn, path_string="runtime/harness")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        downstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            upstream_claim_id=upstream,
        )
        wrong_upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[other_target],
        )
        activate(conn, claim_id=wrong_upstream, base_commit_sha=SNAP)
        release(conn, claim_id=wrong_upstream, reason="merged")
        with pytest.raises(UpstreamNotReleased, match=str(upstream)):
            activate(
                conn,
                claim_id=downstream,
                base_commit_sha=SNAP,
                upstream_claim_id=wrong_upstream,
            )

    def test_activate_serial_downstream_after_upstream_release(self, conn):
        """A blocked downstream can activate once the upstream releases.

        Mirrors the AC-13 lifecycle proxy: the activation gate proves
        the upstream is in a terminal merged state before promoting
        the downstream to ``active``.
        """
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        first = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=first, base_commit_sha=SNAP)
        second = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            upstream_claim_id=first,
        )
        release(conn, claim_id=first, reason="merged-into-main")
        activate(
            conn,
            claim_id=second,
            base_commit_sha=SNAP,
            upstream_claim_id=first,
        )
        assert get_claim(conn, second)["state"] == "active"


class TestReleaseAndCancel:
    def test_release_active_claim(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        release(conn, claim_id=claim_id, reason="merged")
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "released"
        assert claim["release_reason"] == "merged"

    def test_release_idempotent_keeps_first_reason(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        release(conn, claim_id=claim_id, reason="first")
        release(conn, claim_id=claim_id, reason="second")
        assert get_claim(conn, claim_id)["release_reason"] == "first"

    def test_cancel_rejects_after_release(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        release(conn, claim_id=claim_id, reason="merged")
        with pytest.raises(IllegalTransition):
            cancel(conn, claim_id=claim_id, reason="changed-mind")

    def test_release_rejects_after_cancel(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        cancel(conn, claim_id=claim_id, reason="abandoned")
        with pytest.raises(IllegalTransition):
            release(conn, claim_id=claim_id, reason="merged")

    def test_cancel_abandons_unclaimed_planned_targets(self, conn):
        actor = local_human(conn)
        target = plan_path_target(
            conn,
            project_id=1,
            path_string="future/cancelled.py",
            kind=KIND_FILE,
            item_id=1,
        )
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=1,
        )
        cancel(conn, claim_id=claim_id, reason="scope changed")
        state = conn.execute(
            "SELECT materialization_state FROM path_targets WHERE id = %s",
            (target,),
        ).fetchone()["materialization_state"]
        assert state == "abandoned"

    def test_cancel_idempotent(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        cancel(conn, claim_id=claim_id, reason="first")
        cancel(conn, claim_id=claim_id, reason="second")
        assert get_claim(conn, claim_id)["cancel_reason"] == "first"

    def test_get_claim_unknown_id(self, conn):
        with pytest.raises(ClaimNotFound):
            get_claim(conn, 424242)
