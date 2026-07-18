# ruff: noqa: F401, F811
"""Tests for the done-transition Python engine: transition mechanics.
Gates and CLI tests live in test_done_transition_gates.py.
Post-transition (cleanup, cascade, merge) tests live in
test_done_transition_post.py.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

from yoke_core.engines import done_transition
from yoke_core.engines import done_transition_deploy_gates
from yoke_core.engines import done_transition_gates
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_session,
    tmp_db,  # noqa: F401 — fixture re-export
)

from yoke_core.engines._done_transition_test_helpers import (
    _insert_item,
    connect_dt_db,
    dt_db,
)


class TestTransitionResult:
    """TC-result-file: Result file contract."""

    def test_result_writes_valid_json(self, tmp_path):
        result = done_transition.TransitionResult(
            item="YOK-9999",
            exit_code=0,
            old_status="implementing",
            new_status="done",
            merge_ran=True,
        )
        result.add_step("1")
        result.add_step("2")
        path = str(tmp_path / "result.json")
        result.write(path)

        data = json.loads(Path(path).read_text())
        assert data["item"] == "YOK-9999"
        assert data["exit_code"] == 0
        assert data["old_status"] == "implementing"
        assert data["new_status"] == "done"
        assert data["merge_ran"] is True
        assert data["already_completed"] is False
        assert data["steps_completed"] == ["1", "2"]
        assert data["discovery"]["unreviewed_ouroboros"] == 0

    def test_result_fail_sets_code_and_step(self, tmp_path):
        result = done_transition.TransitionResult(item="YOK-99")
        path = str(tmp_path / "result.json")
        code = result.fail(path, 7, "3b")

        assert code == 7
        data = json.loads(Path(path).read_text())
        assert data["exit_code"] == 7
        assert "3b" in data["steps_completed"]

    def test_result_atomic_write_cleans_temp(self, tmp_path):
        result = done_transition.TransitionResult(item="YOK-10")
        path = str(tmp_path / "result.json")
        result.write(path)
        # No .tmp files should remain
        temps = list(tmp_path.glob("result.json.tmp.*"))
        assert temps == []

    def test_load_discovery_metadata_reads_unreviewed_count(self, tmp_path):
        metadata = tmp_path / "discovery.txt"
        metadata.write_text(
            "DISCOVERY_FILE=/tmp/discovery\n"
            "UNREVIEWED_OUROBOROS=3\n"
            "---\n"
        )

        unreviewed = done_transition._load_discovery_metadata(metadata)

        assert unreviewed == 3

    def test_update_status_to_done_defers_github_to_batched_sync(self):
        calls = []

        def fake_update(*args, **kwargs):
            calls.append(kwargs)
            return 0

        with mock.patch.object(done_transition, "_update_item_direct", side_effect=fake_update):
            assert done_transition._update_status_to_done(42, skip_qa=False)

        assert calls
        assert calls[0]["no_github"] is True


class TestResolveRepoRoot:
    def test_uses_python_path_helper(self, tmp_path):
        with mock.patch("yoke_core.engines.done_transition_gates.resolve_main_root", return_value=str(tmp_path)):
            assert done_transition._resolve_repo_root() == tmp_path

    def test_returns_empty_path_on_failure(self, capsys):
        with mock.patch("yoke_core.engines.done_transition_gates.resolve_main_root", side_effect=RuntimeError("boom")):
            assert done_transition._resolve_repo_root() == Path()
        assert "path resolution failed" in capsys.readouterr().err


def test_update_item_direct_exercises_real_backlog_update(tmp_db):
    _seed_item(tmp_db, id=44, type="issue", status="implemented", project="yoke")
    _seed_session(tmp_db, session_id="sess-1")
    _seed_claim(tmp_db, session_id="sess-1", item_id="44")

    with _patch_externals(), \
         mock.patch.dict(
             os.environ,
             {"YOKE_DB": tmp_db, "YOKE_SESSION_ID": "sess-1"},
             clear=False,
         ):
        rc = done_transition._update_item_direct(
            44,
            "status",
            "release",
            env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
        )

    assert rc == 0
    assert _item_field(tmp_db, 44, "status") == "release"


# ---------------------------------------------------------------------------
# Recovery detection tests
# ---------------------------------------------------------------------------


class TestRecovery:
    """TC-recovery: Recovery checkpoint detection."""

    def test_already_done_detected(self):
        done, resume = done_transition._check_recovery("done", "")
        assert done is True
        assert resume is False

    def test_partial_completion_detected(self):
        done, resume = done_transition._check_recovery("implementing", "")
        assert done is False
        assert resume is True

    def test_normal_flow_no_recovery(self):
        done, resume = done_transition._check_recovery("implementing", "YOK-9999")
        assert done is False
        assert resume is False

    def test_done_with_worktree_not_recovery(self):
        """Unusual state: done but worktree still set — not a clean completion."""
        done, resume = done_transition._check_recovery("done", "YOK-9999")
        assert done is False
        assert resume is False


# ---------------------------------------------------------------------------
# Guard logic tests
# ---------------------------------------------------------------------------


class TestDeploymentRedirect:
    """TC-deploy-redirect: Pre-merge deployment flow redirect."""

    def test_redirects_when_flow_present_and_no_skip(self):
        code = done_transition._check_deployment_redirect("standard", False, 42)
        assert code == 7

    def test_passes_when_skip_deploy(self):
        code = done_transition._check_deployment_redirect("standard", True, 42)
        assert code is None

    def test_passes_when_no_flow(self):
        code = done_transition._check_deployment_redirect("", False, 42)
        assert code is None

    def test_passes_when_internal_flow(self):
        code = done_transition._check_deployment_redirect("yoke-internal", False, 42)
        assert code is None


class TestDeploymentEvidence:
    """TC-deploy-evidence: Deployment evidence checks."""

    def test_succeeded_run_is_evidence(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 50, deployment_flow="standard")
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r1', 1, 'succeeded', '2025-01-01')"
        )
        conn.execute("INSERT INTO deployment_run_items (run_id, item_id) VALUES ('r1', 50)")
        conn.commit()
        conn.close()

        assert done_transition._check_deployment_evidence(50) is True

    def test_no_runs_is_no_evidence(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 51, deployment_flow="standard")
        assert done_transition._check_deployment_evidence(51) is False

    def test_failed_run_is_no_evidence(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 52, deployment_flow="standard")
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r2', 1, 'failed', '2025-01-01')"
        )
        conn.execute("INSERT INTO deployment_run_items (run_id, item_id) VALUES ('r2', 52)")
        conn.commit()
        conn.close()

        assert done_transition._check_deployment_evidence(52) is False


class TestDeploymentFlowGuard:
    """TC-deploy-flow-guard: Post-merge deployment flow semantics."""

    def test_skip_deploy_without_evidence_returns_exit_7(self):
        with mock.patch(
            "yoke_core.domain.deployment_flow_validator.list_registered_flow_ids",
            return_value=["externalwebapp-prod-release"],
        ), mock.patch.object(
            done_transition_deploy_gates,
            "_check_deployment_evidence",
            return_value=False,
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=207,
                deploy_flow="externalwebapp-prod-release",
                skip_deploy=True,
                item_project="yoke",
                old_status="implemented",
            )

        assert result == (7, "implemented")

    def test_no_evidence_fallback_sets_release_and_returns_exit_7(self):
        with mock.patch(
            "yoke_core.domain.deployment_flow_validator.list_registered_flow_ids",
            return_value=["externalwebapp-prod-release"],
        ), mock.patch.object(
            done_transition_deploy_gates,
            "_get_latest_run_status",
            return_value=(None, None),
        ):
            with mock.patch.object(
                done_transition,
                "_update_item_direct",
                return_value=0,
            ) as upd:
                result = done_transition._check_deployment_flow_guard(
                    item_id=226,
                    deploy_flow="externalwebapp-prod-release",
                    skip_deploy=False,
                    item_project="yoke",
                    old_status="implemented",
                )

        assert result == (7, "release")
        upd.assert_called_once()
        args, kwargs = upd.call_args
        assert args[0] == 226
        assert args[1] == "status"
        assert args[2] == "release"
        assert kwargs["env_overrides"] == {"YOKE_STATUS_SOURCE": "done-transition"}
        assert kwargs["rebuild_board"] is False


class TestRunStageConsistency:
    """TC-stage-consistency: run stage consistency check."""

    def test_failed_stage_blocks(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, current_stage, created_at) "
            "VALUES ('r3', 1, 'succeeded', 'deploy-failed', '2025-01-01')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_stage_consistency("r3") is True

    def test_normal_stage_passes(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, current_stage, created_at) "
            "VALUES ('r4', 1, 'succeeded', 'deploy', '2025-01-01')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_stage_consistency("r4") is False
