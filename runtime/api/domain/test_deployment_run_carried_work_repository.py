"""A project's repository answers the comparison a checkout would have."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    RELATION_DIVERGED,
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.gh_rest_transport_errors import RestTransportError


BASE = "a" * 40
MERGE = "b" * 40
TIP = "c" * 40


def _commit(sha: str, *, parents: tuple[str, ...], message: str = "") -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {
            "message": message or f"commit {sha[:7]}",
            "committer": {"date": "2026-09-15T00:00:00Z"},
        },
        "parents": [{"sha": parent} for parent in parents],
    }


class _Recorder:
    """Stand in for the REST transport and record every request issued."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.paths: list[str] = []

    def __call__(self, request: Any, *, token: str) -> Any:
        del token
        self.paths.append(request.path)
        answer = self._responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return type("Response", (), {"status": 200, "headers": {}, "body": answer})()


def _source(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> tuple[Any, Any]:
    recorder = _Recorder(responses)
    monkeypatch.setattr(provider, "request_with_retry", recorder)
    return provider.RepositoryProviderSource("owner/repo", "token"), recorder


@pytest.mark.parametrize(
    ("status", "relation"),
    [
        ("ahead", RELATION_AHEAD),
        ("identical", RELATION_AHEAD),
        ("behind", RELATION_DIVERGED),
        ("diverged", RELATION_DIVERGED),
    ],
)
def test_every_compare_status_maps_to_one_lineage_relation(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    relation: str,
):
    """The direction is the whole correctness of this read.

    ``status`` describes the head relative to the base, and the base is the
    older lineage, so a candidate carrying the base reads ``ahead``. Reversing
    it would refuse exactly the releases that must pass.
    """
    source, _recorder = _source(
        monkeypatch,
        [{"status": status, "total_commits": 0, "commits": []}],
    )

    assert source.commit_range(BASE, TIP).relation == relation


def test_the_first_parent_range_is_walked_out_of_the_compared_graph(
    monkeypatch: pytest.MonkeyPatch,
):
    merged_branch_commit = "d" * 40
    source, _recorder = _source(
        monkeypatch,
        [
            {
                "status": "ahead",
                "total_commits": 3,
                "commits": [
                    _commit(MERGE, parents=(BASE,)),
                    _commit(merged_branch_commit, parents=(BASE,)),
                    _commit(TIP, parents=(MERGE, merged_branch_commit)),
                ],
            }
        ],
    )

    commits = source.commit_range(BASE, TIP).commits

    # The side of the merge that is not the first parent is excluded, exactly
    # as `rev-list --first-parent` excludes it in a checkout.
    assert commits == (MERGE, TIP)


def test_a_full_sha_resolves_without_spending_a_request(
    monkeypatch: pytest.MonkeyPatch,
):
    source, recorder = _source(monkeypatch, [])

    assert source.resolve_commit(TIP.upper()) == TIP
    assert recorder.paths == []


def test_an_abbreviated_ref_resolves_to_its_full_object_id(
    monkeypatch: pytest.MonkeyPatch,
):
    """Never pad a prefix into a hash; ask what commit the ref names."""
    source, recorder = _source(monkeypatch, [{"sha": MERGE}])

    assert source.resolve_commit(MERGE[:8]) == MERGE
    assert recorder.paths == [f"/repos/owner/repo/commits/{MERGE[:8]}"]
    # A second ask is served from the cache rather than a second request.
    assert source.resolve_commit(MERGE[:8]) == MERGE
    assert len(recorder.paths) == 1


def test_a_ref_naming_no_commit_resolves_to_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _recorder = _source(
        monkeypatch,
        [RestTransportError("404 not found", status=404)],
    )

    assert source.resolve_commit("no-such-branch") == ""
    assert any(
        warning["reason"] == "lane_branch_refs_unresolvable"
        for warning in source.warnings()
    )


def test_ref_lookups_stay_within_their_budget(monkeypatch: pytest.MonkeyPatch):
    """One request per backlog item is the cost this budget exists to avoid."""
    responses = [{"sha": MERGE}] * provider.COMMIT_LOOKUP_BUDGET
    source, recorder = _source(monkeypatch, responses)

    for index in range(provider.COMMIT_LOOKUP_BUDGET + 3):
        source.resolve_commit(f"branch-{index}")

    assert len(recorder.paths) == provider.COMMIT_LOOKUP_BUDGET


def test_a_lane_commit_outside_the_range_carries_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _recorder = _source(
        monkeypatch,
        [
            {
                "status": "ahead",
                "total_commits": 1,
                "commits": [_commit(TIP, parents=(BASE,))],
            }
        ],
    )
    commits = source.commit_range(BASE, TIP).commits

    assert source.carrying_commit(TIP, base=BASE, head=TIP, commits=commits) == TIP
    assert source.carrying_commit(BASE, base=BASE, head=TIP, commits=commits) == ""


def test_an_unreadable_provider_names_itself_rather_than_answering_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _recorder = _source(
        monkeypatch,
        [RestTransportError("503 unavailable", status=503)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert raised.value.reason == "repository_provider_read_failed"


def test_a_comparison_beyond_the_page_budget_refuses_instead_of_truncating(
    monkeypatch: pytest.MonkeyPatch,
):
    page = {
        "status": "ahead",
        "total_commits": 10_000,
        "commits": [_commit(f"{index:040x}", parents=(BASE,)) for index in range(100)],
    }
    source, _recorder = _source(
        monkeypatch,
        [dict(page) for _ in range(provider.COMPARE_PAGE_LIMIT)],
    )

    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        source.commit_range(BASE, TIP)

    assert raised.value.reason == "carried_range_exceeds_provider_page_limit"
