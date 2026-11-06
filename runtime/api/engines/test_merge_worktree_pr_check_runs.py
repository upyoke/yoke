"""GraphQL pull-request projection: landing status and required checks together."""

from __future__ import annotations

from runtime.api.engines.merge_worktree_pr_check_runs_test_support import (
    _auth as _auth,
    _check_run as _check_run,
    _ctx as _ctx,
    _pr_node as _pr_node,
    _wire as _wire,
)


from copy import deepcopy

import pytest
from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import merge_github_check_runs as checks_mod


def test_open_armed_pr_and_pending_required_check(monkeypatch) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            auto_merge=True,
            merge_state="BLOCKED",
            contexts=(_check_run(name="repo-contracts", status="IN_PROGRESS"),),
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


@pytest.mark.parametrize(
    "clock",
    [
        "2026-09-21T12:00:00Z",
        "2026-09-21T17:45:00.123456+05:45",
        "2026-09-21T08:00:00.123456-04:00",
    ],
)
def test_merged_pr_carries_commit_and_time(monkeypatch, clock) -> None:
    _wire(
        monkeypatch,
        _pr_node(
            merged=True,
            closed=True,
            state="MERGED",
            merged_at=clock,
            merge_oid="def456",
            contexts=(),
        ),
    )

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "7")

    assert projection.state is not None
    assert projection.state.merged
    assert projection.state.closed
    assert projection.state.merged_at == parse_instant(clock)
    assert projection.state.merged_at.utcoffset().total_seconds() == 0
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
    assert "mergeQueueEntry { state }" in query
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


@pytest.mark.parametrize("kind", ["CheckRun", "StatusContext"])
@pytest.mark.parametrize(
    "earlier,later",
    [
        ("2026-09-21T05:45:00.123456+05:45", "2026-09-21T00:00:00.123457Z"),
        ("2026-09-21T00:00:00.123456Z", "2026-09-20T20:00:00.123456-04:00"),
        (None, "1969-12-31T23:59:59.123456Z"),
    ],
)
def test_required_check_selection_compares_native_instants(
    monkeypatch, kind, earlier, later
):
    nodes = []
    for clock, verdict in ((earlier, "failure"), (later, "success")):
        node = _check_run(
            name="repo-contracts", status="COMPLETED", conclusion=verdict, started=clock
        )
        if kind == "StatusContext":
            node = {
                "__typename": kind,
                "context": "repo-contracts",
                "state": verdict,
                "createdAt": clock,
                "isRequired": True,
                "targetUrl": "opaque/url",
            }
        nodes.append(node)
    payload = _pr_node(contexts=nodes)
    original = deepcopy(payload)
    _wire(monkeypatch, payload)
    checks, err = checks_mod.read_required_checks(_ctx(), "42")
    assert err is None
    assert checks[0].conclusion == "success"
    assert payload == original


@pytest.mark.parametrize("kind", ["CheckRun", "StatusContext"])
@pytest.mark.parametrize(
    "clock", ["2026-09-21", "2026-09-21T00:00:00", "2026-09-21T00:00:00-00:00"]
)
def test_invalid_required_check_clock_makes_projection_unreadable(
    monkeypatch, kind, clock
):
    node = _check_run(
        name="repo-contracts", status="COMPLETED", conclusion="SUCCESS", started=clock
    )
    if kind == "StatusContext":
        node = {
            "__typename": kind,
            "context": "repo-contracts",
            "state": "SUCCESS",
            "createdAt": clock,
            "isRequired": True,
            "targetUrl": "opaque/url",
        }
    _wire(monkeypatch, _pr_node(contexts=[node]))
    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")
    assert projection.state is None
    assert projection.required_checks is None
    assert "clock" in projection.checks_error
    assert projection.state_error == projection.checks_error
