"""Doctor coverage for project-scoped, proof-gated remote cleanup."""

from unittest.mock import Mock, patch

import pytest

from runtime.api.engines.test_doctor_git_worktrees import (
    _make_completed,
    _make_conn,
    _run_hc,
)
from yoke_core.domain.item_refs_schema import ensure_item_refs_view
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.engines import doctor_hc_worktrees_branches as checks
from yoke_core.engines._project_identity_test_helpers import _insert_item, _seed_project
from yoke_core.engines.remote_branch_cleanup import RemoteBranchDeleteResult

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def conn():
    database = _make_conn()
    ensure_item_refs_view(database)
    yield database
    database.close()


@pytest.fixture
def remote(monkeypatch, tmp_path):
    monkeypatch.setattr(checks, "checkout_for_project_id", lambda _: str(tmp_path))
    remote = Mock(return_value=_make_completed())
    monkeypatch.setattr(checks._credentialed_git, "run", remote)
    return remote


def test_no_checkout_is_not_applicable(conn, monkeypatch, remote):
    monkeypatch.setattr(checks, "checkout_for_project_id", lambda _: None)
    result = _run_hc(checks.hc_stale_remote_branches, conn, fix=True).results[0]
    assert result.result == "N/A"
    assert result.detail == "this runner has no checkout for it"
    remote.assert_not_called()


def test_inspected_empty_remote_passes(conn, remote):
    result = _run_hc(checks.hc_stale_remote_branches, conn).results[0]
    assert result.result == "PASS"
    assert remote.call_count == 1


@pytest.mark.parametrize("project", ["yoke", "1"])
def test_only_selected_project_is_read(conn, remote, monkeypatch, tmp_path, project):
    _seed_project(conn, "externalwebapp")
    resolved = []

    def checkout(project_id):
        resolved.append(project_id)
        return str(tmp_path)

    monkeypatch.setattr(checks, "checkout_for_project_id", checkout)
    _run_hc(checks.hc_stale_remote_branches, conn, project=project)
    assert resolved == [1]
    assert remote.call_count == 1
    assert remote.call_args.args[0] == [
        "-C",
        str(tmp_path),
        "ls-remote",
        "--heads",
        "origin",
    ]


def test_stale_branch_warns_without_mutation(conn, remote):
    _insert_item(conn, TEST_ITEM_ID, status="done")
    remote.return_value = _make_completed(
        stdout=f"branch-sha\trefs/heads/{TEST_ITEM_REF}\n"
    )
    result = _run_hc(checks.hc_stale_remote_branches, conn).results[0]
    assert result.result == "WARN"
    assert TEST_ITEM_REF in result.detail
    assert "--fix" in result.detail
    assert remote.call_count == 1


@pytest.mark.parametrize("authority", ["claim", "unavailable"])
def test_fix_preserves_active_or_unproven_authority(conn, remote, authority):
    _insert_item(conn, TEST_ITEM_ID, status="done")
    if authority == "claim":
        target = make_item_target(TEST_ITEM_ID)
        conn.execute(
            "INSERT INTO work_claims "
            "(id, session_id, target_kind, scope, released_at) "
            "VALUES (1, 'active', %s, %s, NULL)",
            (target.kind, target.scope_json()),
        )
    else:
        conn.execute("DROP TABLE path_claims")
    remote.return_value = _make_completed(
        stdout=f"branch-sha\trefs/heads/{TEST_ITEM_REF}\n"
    )
    result = _run_hc(checks.hc_stale_remote_branches, conn, fix=True).results[0]
    assert result.result == "WARN"
    assert "cleanup authority is active or could not be proven idle" in result.detail
    assert remote.call_count == 1


def test_remote_candidates_use_one_set_query_and_fetch(conn, remote, monkeypatch):
    # Thousands of terminal items must not produce thousands of item reads.
    conn.execute(
        "INSERT INTO items (id, title, status, project_id, project_sequence) "
        "SELECT n, 'done', 'done', 1, n FROM generate_series(100, 5100) n"
    )
    for item_id, status in (
        (42, "done"),
        (43, "done"),
        (44, "implementing"),
        (45, "cancelled"),
    ):
        _insert_item(conn, item_id, status=status)
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id, item_id, branch, lane_role, state, created_at, updated_at) "
        "VALUES (1, 43, 'recorded-lane', 'implementation', 'active', now(), now()), "
        "(2, 45, 'retired-lane', 'implementation', 'released', now(), now())"
    )
    branches = {
        "main": "base",
        TEST_ITEM_REF: "done",
        "recorded-lane": "lane",
        "YOK-44": "open",
        "retired-lane": "cancelled",
    }
    remote.return_value = _make_completed(
        stdout="".join(
            f"{sha}\trefs/heads/{branch}\n" for branch, sha in branches.items()
        )
    )
    delete = Mock(
        return_value=RemoteBranchDeleteResult("deleted", "remote branch was deleted")
    )
    monkeypatch.setattr(checks, "delete_remote_branch_if_merged", delete)
    with patch.object(checks, "query_rows", wraps=checks.query_rows) as queries:
        result = _run_hc(checks.hc_stale_remote_branches, conn, fix=True).results[0]
    assert queries.call_count == 2  # projects plus one branch-matching set query
    assert "ANY(%s)" in queries.call_args.args[1]
    assert queries.call_args.args[2] == (list(branches), list(branches), 1)
    assert result.result == "WARN"
    assert "recorded-lane [yoke]: lane sweep owns it" in result.detail
    assert "deleted 2" in result.detail
    assert {call.kwargs["branch"] for call in delete.call_args_list} == {
        TEST_ITEM_REF,
        "retired-lane",
    }
    assert all(
        call.kwargs["refreshed_branches"] == branches for call in delete.call_args_list
    )
    commands = [call.args[0][2:] for call in remote.call_args_list]
    assert commands == [
        ["ls-remote", "--heads", "origin"],
        ["fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"],
    ]


@pytest.mark.parametrize("failure", ["list", "fetch"])
def test_remote_failure_warns_and_teaches_recovery(conn, remote, monkeypatch, failure):
    _insert_item(conn, TEST_ITEM_ID, status="done")
    failed = _make_completed(returncode=1, stderr="origin unavailable")
    remote.side_effect = (
        [failed]
        if failure == "list"
        else [_make_completed(stdout=f"sha\trefs/heads/{TEST_ITEM_REF}\n"), failed]
    )
    delete = Mock()
    monkeypatch.setattr(checks, "delete_remote_branch_if_merged", delete)
    result = _run_hc(checks.hc_stale_remote_branches, conn, fix=True).results[0]
    assert result.result == "WARN"
    assert "restore origin access and rerun" in result.detail
    delete.assert_not_called()
