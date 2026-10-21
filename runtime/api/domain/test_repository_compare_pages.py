"""A comparison between two pinned commits is asked of the host once."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_repository as provider

BASE = "a" * 40
TIP = "c" * 40


def _page() -> dict[str, Any]:
    return {
        "status": "ahead",
        "total_commits": 1,
        "commits": [
            {
                "sha": TIP,
                "commit": {
                    "message": "tip",
                    "committer": {"date": "2026-09-15T00:00:00Z"},
                    "author": {"name": "A contributor"},
                },
                "parents": [{"sha": BASE}],
            }
        ],
    }


def _record_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    paths: list[str] = []

    def request(rest_request: Any, *, token: str) -> Any:
        del token
        paths.append(rest_request.path)
        if "/compare/" not in rest_request.path:
            return type("Response", (), {"status": 200, "body": {"sha": TIP}})()
        return type("Response", (), {"status": 200, "body": _page()})()

    monkeypatch.setattr(provider, "request_with_retry", request)
    return paths


def test_each_poll_reuses_the_comparison_of_pinned_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _record_requests(monkeypatch)

    # Every request opens its own source, as each execution-context poll does.
    answers = [
        provider.RepositoryProviderSource("owner/repo", "token").commit_range(
            BASE, TIP
        )
        for _ in range(3)
    ]

    assert [answer.commits for answer in answers] == [(TIP,)] * 3
    assert paths == [f"/repos/owner/repo/compare/{BASE}...{TIP}"]


def test_a_comparison_naming_a_branch_is_asked_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _record_requests(monkeypatch)

    for _ in range(2):
        provider.RepositoryProviderSource("owner/repo", "token").lineage_relation(
            BASE, "main"
        )

    assert paths == [f"/repos/owner/repo/compare/{BASE}...main"] * 2


def test_another_repository_does_not_share_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _record_requests(monkeypatch)

    for repo in ("owner/repo", "owner/other"):
        provider.RepositoryProviderSource(repo, "token").commit_range(BASE, TIP)

    assert len(paths) == 2
