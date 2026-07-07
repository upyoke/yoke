"""migration_apply — live-apply happy path and refusal branches.

Split out of ``test_migration_apply.py`` to keep authored files under the
350-line limit. Heavy fixture/helper code lives in
``migration_apply_test_helpers``.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import (
    LeaseHeldError,
    acquire_lease,
)
from yoke_core.domain.migration_apply import (
    CompatibilityClassError,
    LEASE_KEY_PREFIX,
    LiveApplyResult,
    RehearsalMissingError,
    RehearsalStaleError,
    STATE_COMPLETED,
    STATE_REHEARSED,
    live_apply,
    rehearse,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _audit_row,
    _seed_apply_item,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


class TestLiveApplyHappyPath:
    def test_live_apply_after_rehearse_completes(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5020)
        rehearse_result = rehearse(
            5020,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        assert rehearse_result.all_succeeded

        apply_result = live_apply(
            5020,
            session_id="test-live-apply",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        assert isinstance(apply_result, LiveApplyResult)
        assert apply_result.all_succeeded
        assert apply_result.lease_id is not None
        mod = apply_result.modules[0]
        assert mod.state == STATE_COMPLETED
        row = _audit_row(apply_env["authoritative_db"], mod.audit_id)
        assert row["state"] == STATE_COMPLETED
        assert row["backup_path"]
        # Backup file must exist.
        assert os.path.isfile(row["backup_path"])
        # Authoritative DB now has widgets.
        with db_backend.connect_psycopg(apply_env["authoritative_db"]) as auth:
            live_has = _table_exists(auth, "widgets")
        assert live_has

    def test_lease_released_on_success(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5021)
        rehearse(
            5021,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        live_apply(
            5021,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            row = conn.execute(
                "SELECT released_at, release_reason FROM coordination_leases "
                "WHERE project_id = %s AND lease_key = %s "
                "ORDER BY id DESC LIMIT 1",
                (1, f"{LEASE_KEY_PREFIX}primary"),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] is not None  # released_at set
        assert row[1] == "live-apply-complete"


class TestLiveApplyRefusal:
    def test_refuses_when_strategy_matrix_blocks(self, apply_env) -> None:
        # founder_cutover + expand_contract (no justification) is a matrix block.
        # The fixture stages a project with breakage_policy=founder_cutover by
        # default; we override the seeded profile to declare expand_contract.
        _seed_apply_item(
            apply_env["control_db"],
            item_id=5029,
            compatibility_class="pre_merge_safe",
        )
        # Patch the profile to declare expand_contract without justification.
        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            row = conn.execute(
                "SELECT db_mutation_profile FROM items WHERE id=%s", (5029,)
            ).fetchone()
            import json
            profile = json.loads(row[0])
            profile["migration_strategy"] = "expand_contract"
            conn.execute(
                "UPDATE items SET db_mutation_profile=%s WHERE id=%s",
                (json.dumps(profile, sort_keys=True), 5029),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(CompatibilityClassError) as exc:
            live_apply(
                5029,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
        assert "expand_contract" in str(exc.value)
        assert "founder_cutover" in str(exc.value)

        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM coordination_leases"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0

    def test_refuses_missing_rehearsal(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5030)
        with pytest.raises(RehearsalMissingError):
            live_apply(
                5030,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
        # No lease was acquired.
        conn = db_backend.connect_psycopg(apply_env["authoritative_db"])
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM coordination_leases"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0

    def test_refuses_fingerprint_mismatch(self, apply_env) -> None:
        """AC-62: authoritative-DB schema change after rehearsal refuses live-apply."""
        _seed_apply_item(apply_env["control_db"], item_id=5031)
        rehearse(
            5031,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        # Out-of-band schema change to the authoritative DB.
        with db_backend.connect_psycopg(apply_env["authoritative_db"]) as auth:
            auth.execute("CREATE TABLE drift_marker (id INTEGER)")
            auth.commit()
        with pytest.raises(RehearsalStaleError) as exc:
            live_apply(
                5031,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
        assert "fingerprint" in str(exc.value)

    def test_refuses_freshness_expired(self, apply_env) -> None:
        """AC-62: rehearsed_at older than 30m refuses live-apply."""
        _seed_apply_item(apply_env["control_db"], item_id=5032)
        rehearse(
            5032,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        # Age the rehearsed_at to > 30m past.
        with db_backend.connect_psycopg(apply_env["authoritative_db"]) as auth:
            auth.execute(
                "UPDATE migration_audit SET rehearsed_at = %s "
                "WHERE state = %s",
                ("2000-01-01T00:00:00Z", STATE_REHEARSED),
            )
            auth.commit()
        with pytest.raises(RehearsalStaleError) as exc:
            live_apply(
                5032,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
        assert "window" in str(exc.value)

    def test_refuses_held_lease(self, apply_env) -> None:
        """AC-63 supporting: a live holder on the per-model lease blocks live-apply."""
        _seed_apply_item(apply_env["control_db"], item_id=5033)
        rehearse(
            5033,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        conn = _conn(apply_env["control_db"])
        try:
            acquire_lease(
                conn, "yoke", f"{LEASE_KEY_PREFIX}primary",
                "other-session",
            )
        finally:
            conn.close()
        with pytest.raises(LeaseHeldError):
            live_apply(
                5033,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )


class TestLiveApplyProvenance:
    def test_audit_row_carries_provenance(self, apply_env) -> None:
        _seed_apply_item(apply_env["control_db"], item_id=5040)
        rehearse(
            5040,
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        apply_result = live_apply(
            5040,
            session_id="prov-sess",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
        mod = apply_result.modules[0]
        row = _audit_row(apply_env["authoritative_db"], mod.audit_id)
        assert row["state"] == STATE_COMPLETED
        # Provenance columns are stamped from the live-apply path.
        assert row["worktree"] == str(apply_env["worktree"])
        assert row["integration_target"] == "main"
        assert row["change_class"] == "additive_only"
        assert row["lease_id"] == apply_result.lease_id
        # source_branch / source_commit may be None when the test fixture
        # has not initialized a git worktree; both should at least be the
        # column-present nullable shape rather than absent keys.
        assert "source_branch" in row.keys()
        assert "source_commit" in row.keys()
