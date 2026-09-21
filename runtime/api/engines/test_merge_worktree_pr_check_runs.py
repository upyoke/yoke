"""GraphQL pull-request projection: landing status and required checks together."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.engines import merge_worktree_pr_check_runs as checks_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-3361"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _check_run(*, name, status, conclusion="", required=True, started="2026-09-21T00:00:00Z"):
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": f"https://example/{name}",
        "startedAt": started,
        "isRequired": required,
    }


def _pr_node(
    *,
    merged=False,
    closed=False,
    state="OPEN",
    auto_merge=False,
    merge_state="CLEAN",
    head="abc123def",
    merged_at="",
    merge_oid="",
    rollup="present",
    contexts=(),
):
    commit = {"statusCheckRollup": None}
    if rollup == "present":
        commit["statusCheckRollup"] = {"contexts": {"nodes": list(contexts)}}
    elif rollup == "missing":
        commit = {}
    node = {
        "merged": merged,
        "closed": closed,
        "state": state,
        "autoMergeRequest": {"enabledAt": "2026-09-21T00:00:00Z"} if auto_merge else None,
        "mergeStateStatus": merge_state,
        "headRefOid": head,
        "mergedAt": merged_at or None,
        "mergeCommit": {"oid": merge_oid} if merge_oid else None,
        "commits": {"nodes": [{"commit": commit}]},
    }
    return {"repository": {"pullRequest": node}}


def _wire(monkeypatch, payload, err=None, *, capture=None):
    monkeypatch.setattr(
        checks_mod, "resolve_auth_detail", lambda _ctx, _perms: (_auth(), None)
    )

    def fake_graphql(_auth, *, query, variables, required_permissions):
        if capture is not None:
            capture.append({"query": query, "variables": variables})
        return payload, err

    monkeypatch.setattr(checks_mod, "graphql_with_auth", fake_graphql)


def test_open_armed_pr_and_pending_required_check(monkeypatch) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            auto_merge=True,
            merge_state="BLOCKED",
            contexts=(
                _check_run(name="repo-contracts", status="IN_PROGRESS"),
            ),
        ),
    )

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")

    assert projection.state_error is None
    assert projection.state is not None
    assert not projection.state.merged
    assert not projection.state.closed
    assert projection.state.auto_merge_active
    assert projection.state.merge_state_status == "blocked"
    assert projection.state.head_sha == "abc123def"
    assert projection.required_checks == (
        checks_mod.LandingCheck(
            name="repo-contracts",
            status="in_progress",
            required=True,
            url="https://example/repo-contracts",
        ),
    )


def test_merged_pr_carries_commit_and_time(monkeypatch) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            merged=True,
            closed=True,
            state="MERGED",
            merged_at="2026-09-21T12:00:00Z",
            merge_oid="def456",
            contexts=(),
        ),
    )

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "7")

    assert projection.state is not None
    assert projection.state.merged
    assert projection.state.closed
    assert projection.state.merged_at == "2026-09-21T12:00:00Z"
    assert projection.state.merge_commit_sha == "def456"
    assert projection.required_checks == ()


def test_closed_unmerged_pr(monkeypatch) -> None:
    _wire(monkeypatch, _pr_node(closed=True, state="CLOSED"))

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "9")

    assert projection.state is not None
    assert not projection.state.merged
    assert projection.state.closed


def test_failing_required_check_and_ignored_optional(monkeypatch) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            contexts=(
                _check_run(
                    name="repo-contracts", status="COMPLETED", conclusion="FAILURE"
                ),
                _check_run(
                    name="lint-advisory",
                    status="COMPLETED",
                    conclusion="FAILURE",
                    required=False,
                ),
            )
        ),
    )

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")
    names = [check.name for check in (projection.required_checks or ())]
    assert names == ["repo-contracts"]
    assert projection.required_checks[0].conclusion == "failure"


def test_absent_rollup_is_empty_not_success(monkeypatch) -> None:
    _wire(monkeypatch, _pr_node(rollup="absent"))

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")

    assert projection.state is not None
    assert projection.required_checks == ()
    assert projection.checks_error is None


def test_inaccessible_pr_is_unreadable(monkeypatch) -> None:
    _wire(monkeypatch, {"repository": {"pullRequest": None}})

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")

    assert projection.state is None
    assert projection.required_checks is None
    assert "no pull request 42" in (projection.state_error or "")
    assert projection.checks_error == projection.state_error


def test_graphql_errors_fail_the_whole_document(monkeypatch) -> None:
    _wire(monkeypatch, None, "github graphql refused: something went wrong")

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")

    assert projection.state is None
    assert projection.required_checks is None
    assert "pull-request landing read failed" in (projection.state_error or "")
    assert "something went wrong" in (projection.checks_error or "")


def test_invalid_pr_identifier_does_not_call_github(monkeypatch) -> None:
    calls: list[object] = []
    _wire(monkeypatch, _pr_node(), capture=calls)

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "not-a-number")

    assert calls == []
    assert projection.state is None
    assert "not a number" in (projection.state_error or "")


def test_one_document_asks_for_landing_fields_and_the_rollup(monkeypatch) -> None:
    calls: list[dict] = []
    _wire(monkeypatch, _pr_node(), capture=calls)

    checks_mod.read_required_checks(_ctx(), "42")

    assert len(calls) == 1
    query = calls[0]["query"]
    assert "mergeStateStatus" in query
    assert "statusCheckRollup" in query
    assert "autoMergeRequest" in query
    assert calls[0]["variables"] == {
        "owner": "upyoke",
        "name": "yoke",
        "number": 42,
    }


def test_latest_required_run_wins_by_start_time(monkeypatch) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            contexts=(
                _check_run(
                    name="repo-contracts",
                    status="COMPLETED",
                    conclusion="FAILURE",
                    started="2026-09-21T00:00:00Z",
                ),
                _check_run(
                    name="repo-contracts",
                    status="COMPLETED",
                    conclusion="SUCCESS",
                    started="2026-09-21T01:00:00Z",
                ),
            )
        ),
    )

    checks, err = checks_mod.read_required_checks(_ctx(), "42")
    assert err is None
    assert checks == (
        checks_mod.LandingCheck(
            name="repo-contracts",
            status="completed",
            conclusion="success",
            required=True,
            url="https://example/repo-contracts",
        ),
    )
