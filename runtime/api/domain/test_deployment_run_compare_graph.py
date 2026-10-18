"""Each comparison is counted alone, and a refusal is a prepared answer."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain.deployment_prepared_source import PreparedSource
from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.deployment_source_reads import (
    SourcePreparationChanged,
    prepared_sources_only,
)
from yoke_core.domain.schema_read_scope import composition_reads

OLDER = "a" * 40
BASE = "b" * 40
MIDDLE = "d" * 40
HEAD = "c" * 40


def _commit(sha: str, parent: str) -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {
            "message": f"commit {sha[:7]}",
            "committer": {"date": "2026-10-17T00:00:00Z"},
            "author": {"name": "A contributor"},
        },
        "parents": [{"sha": parent}],
    }


COMPARISONS = {
    (OLDER, HEAD): [_commit(BASE, OLDER), _commit(MIDDLE, BASE), _commit(HEAD, MIDDLE)],
    (BASE, HEAD): [_commit(MIDDLE, BASE), _commit(HEAD, MIDDLE)],
}


def _provider(request: Any, *, token: str) -> Any:
    del token
    base, head = request.path.rsplit("/", 1)[-1].split("...")
    commits = COMPARISONS[(base, head)]
    body = {"status": "ahead", "total_commits": len(commits), "commits": commits}
    return type("Response", (), {"status": 200, "headers": {}, "body": body})()


def test_a_shorter_comparison_after_a_longer_one_is_counted_alone(monkeypatch):
    """The longer range's commits are not this range's, nor its walk's."""
    monkeypatch.setattr(provider, "request_with_retry", _provider)
    source = provider.RepositoryProviderSource("owner/repo", "token")

    longer = source.commit_range(OLDER, HEAD)
    shorter = source.commit_range(BASE, HEAD)

    assert longer.relation == shorter.relation == RELATION_AHEAD
    assert longer.commits == (BASE, MIDDLE, HEAD)
    assert shorter.commits == (MIDDLE, HEAD)
    assert source.carrying_commit(BASE, base=BASE, head=HEAD, commits=(HEAD,)) == ""
    assert source.carrying_commit(BASE, base=OLDER, head=HEAD, commits=(HEAD,)) == HEAD
    assert source.commit_message(MIDDLE) == "commit ddddddd"


class _RefusingSource:
    origin = "repository_provider"
    location = "owner/repo"

    def commit_range(self, base: str, head: str) -> Any:
        raise CarriedWorkSourceUnavailable(
            "repository_provider_comparison_incomplete", "retry later."
        )


def test_a_refusal_found_by_preparation_reaches_the_caller_that_asked():
    """Preparation keeps the refusal; the locked question re-raises it."""
    conn = object()
    with composition_reads():
        source = PreparedSource(conn, ("carried_source", 1, ""), _RefusingSource())
        with pytest.raises(SourcePreparationChanged) as changed:
            with prepared_sources_only():
                source.commit_range(BASE, HEAD)
        changed.value.prepare()
        with pytest.raises(CarriedWorkSourceUnavailable) as refused:
            with prepared_sources_only():
                source.commit_range(BASE, HEAD)
    assert refused.value.reason == "repository_provider_comparison_incomplete"
