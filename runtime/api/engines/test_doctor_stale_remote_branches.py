"""Doctor coverage for proof-gated stale remote branch cleanup."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.engines.test_doctor_git_worktrees import (
    _make_completed,
    _make_conn,
    _run_hc,
)
from yoke_core.engines import doctor_hc_worktrees_branches
from yoke_core.engines._project_identity_test_helpers import (
    _insert_item,
    _seed_project,
)
from yoke_core.engines.doctor import hc_stale_remote_branches
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestHcStaleRemoteBranches:
    """Stale remote branches are deleted only after positive safety proof."""

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_no_stale_branches_passes(self, mock_run, mock_root):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        mock_run.side_effect = [
            _make_completed(stdout=""),
            _make_completed(stdout=""),
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        assert rec.results[0].result == "PASS"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_stale_branch_warns(self, mock_run, mock_root):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, TEST_ITEM_ID, "Done item", type="issue", status="done")
        mock_run.side_effect = [
            _make_completed(stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"),
            _make_completed(stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"),
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        assert rec.results[0].result == "WARN"
        assert TEST_ITEM_REF in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_fix_uses_proof_gated_remote_cleanup(
        self, mock_run, mock_root, monkeypatch
    ):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, TEST_ITEM_ID, "Done item", type="issue", status="done")
        mock_run.side_effect = [
            _make_completed(stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"),
        ]
        monkeypatch.setattr(
            doctor_hc_worktrees_branches,
            "checkout_for_project_id",
            lambda project_id: None,
        )
        calls = []

        def safe_delete(**kwargs):
            calls.append(kwargs)
            return RemoteBranchDeleteResult("deleted", "remote branch was deleted")

        monkeypatch.setattr(
            doctor_hc_worktrees_branches,
            "delete_remote_branch_if_merged",
            safe_delete,
        )

        rec = _run_hc(hc_stale_remote_branches, conn, fix=True)

        assert rec.results[0].result == "PASS"
        assert len(calls) == 1
        assert calls[0]["branch"] == TEST_ITEM_REF
        assert calls[0]["target_branch"] == "main"
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert not any("--delete" in command for command in commands)

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_fix_preserves_branch_with_active_authority(
        self, mock_run, mock_root, monkeypatch
    ):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, TEST_ITEM_ID, "Done item", type="issue", status="done")
        conn.execute(
            "INSERT INTO work_claims "
            "(id, session_id, target_kind, item_id, released_at) "
            f"VALUES (1, 'active', 'item', {TEST_ITEM_ID}, NULL)"
        )
        mock_run.side_effect = [
            _make_completed(stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"),
        ]
        monkeypatch.setattr(
            doctor_hc_worktrees_branches,
            "checkout_for_project_id",
            lambda project_id: None,
        )

        rec = _run_hc(hc_stale_remote_branches, conn, fix=True)

        assert rec.results[0].result == "WARN"
        assert "PRESERVED" in rec.results[0].detail
        assert "active or could not be proven idle" in rec.results[0].detail
        assert mock_run.call_count == 1

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_fix_preserves_branch_when_authority_proof_is_unavailable(
        self, mock_run, mock_root, monkeypatch
    ):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, TEST_ITEM_ID, "Done item", type="issue", status="done")
        conn.execute("DROP TABLE path_claims")
        mock_run.side_effect = [
            _make_completed(stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"),
        ]
        monkeypatch.setattr(
            doctor_hc_worktrees_branches,
            "checkout_for_project_id",
            lambda project_id: None,
        )

        rec = _run_hc(hc_stale_remote_branches, conn, fix=True)

        assert rec.results[0].result == "WARN"
        assert "PRESERVED" in rec.results[0].detail
        assert mock_run.call_count == 1

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_fix_never_uses_default_repo_for_an_unavailable_project_checkout(
        self, mock_run, mock_root, monkeypatch
    ):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp")
        _insert_item(
            conn,
            TEST_ITEM_ID,
            "Done ExternalWebapp item",
            project="externalwebapp",
            type="issue",
            status="done",
        )
        monkeypatch.setattr(
            doctor_hc_worktrees_branches,
            "checkout_for_project_id",
            lambda project_id: None,
        )
        mock_run.return_value = _make_completed(
            stdout=f"abc123\trefs/heads/{TEST_ITEM_REF}\n"
        )
        safe_delete = patch.object(
            doctor_hc_worktrees_branches,
            "delete_remote_branch_if_merged",
        )

        with safe_delete as delete:
            rec = _run_hc(hc_stale_remote_branches, conn, fix=True)

        assert rec.results[0].result == "PASS"
        delete.assert_not_called()
        assert mock_run.call_count == 1
