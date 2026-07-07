"""migration_apply — live-verify failure recovery and profile gating.

Split out of ``test_migration_apply.py`` to keep authored files under the
350-line limit. Heavy fixture/helper code lives in
``migration_apply_test_helpers``.
"""

from __future__ import annotations

import json
import os

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain.migration_apply import (
    LEASE_KEY_PREFIX,
    MigrationApplyError,
    ProfileNotApplyError,
    live_apply,
    rehearse,
)
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _LIVE_VERIFY_TRIP_BODY,
    _audit_row,
    _seed_apply_item,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


class TestLiveApplyFailure:
    """AC-50: live-verify failure preserves backup and releases lease with reason."""

    def test_live_verify_failure_marks_audit_and_releases_lease(
        self, apply_env, monkeypatch
    ) -> None:
        from yoke_core.domain.migration_apply import FAIL_LIVE_VERIFY

        (apply_env["modules_dir"] / "live_verify_trip.py").write_text(
            _LIVE_VERIFY_TRIP_BODY, encoding="utf-8",
        )
        _seed_apply_item(
            apply_env["control_db"], item_id=5050,
            modules=["live_verify_trip"],
        )
        # Rehearse passes (trip unset).
        monkeypatch.delenv("YOKE_TRIP_LIVE_VERIFY", raising=False)
        rehearse(
            5050,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        # Trip the invariant for live-apply only.
        monkeypatch.setenv("YOKE_TRIP_LIVE_VERIFY", "1")
        result = live_apply(
            5050,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        assert not result.all_succeeded
        mod = result.modules[0]
        assert mod.state == FAIL_LIVE_VERIFY
        assert "synthetic live-verify failure" in mod.error

        row = _audit_row(apply_env["authoritative_db"], mod.audit_id)
        assert row["state"] == FAIL_LIVE_VERIFY
        # Backup was created before apply, so the path must exist.
        assert row["backup_path"]
        assert os.path.isfile(row["backup_path"])

        # Lease was released with a live-verify-failed reason.
        conn = _conn(apply_env["control_db"])
        try:
            lease_row = conn.execute(
                "SELECT released_at, release_reason FROM coordination_leases "
                "WHERE project_id = %s AND lease_key = %s "
                "ORDER BY id DESC LIMIT 1",
                (1, f"{LEASE_KEY_PREFIX}primary"),
            ).fetchone()
        finally:
            conn.close()
        assert lease_row[0] is not None
        assert lease_row[1].startswith("live-verify-failed:")

        # Provenance columns are stamped even on the failure path so the
        # audit row records who/what touched the authoritative DB.
        assert row["worktree"] == str(apply_env["worktree"])
        assert row["integration_target"] == "main"
        assert row["change_class"] == "additive_only"


class TestProfileGating:
    def test_state_none_profile_refused(self, apply_env) -> None:
        conn = _conn(apply_env["control_db"])
        try:
            insert_item(
                conn,
                id=5040,
                project="yoke",
                status="implementing",
                db_mutation_profile=json.dumps({"state": "none"}),
            )
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(ProfileNotApplyError):
            rehearse(
                5040,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )

    def test_retire_intent_refused_by_rehearse(self, apply_env) -> None:
        _seed_apply_item(
            apply_env["control_db"], item_id=5041, intent="retire",
        )
        with pytest.raises(ProfileNotApplyError):
            rehearse(
                5041,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )

    def test_unknown_item_raises(self, apply_env) -> None:
        with pytest.raises(MigrationApplyError):
            rehearse(
                9999,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
