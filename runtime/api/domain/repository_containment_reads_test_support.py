# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_repository as provider

from yoke_core.domain import repository_content_equivalence as equivalence

from yoke_core.domain.gh_rest_transport_errors import RestNotFoundError

CANDIDATE = "c" * 40

COMMIT = "b" * 40


class _Answers:
    """Answer each request by path, recording the order they arrived in."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self._answers = answers
        self.paths: list[str] = []

    def __call__(self, request: Any, *, token: str) -> Any:
        del token
        self.paths.append(request.path)
        answer = self._answers[request.path]
        if isinstance(answer, Exception):
            raise answer
        return type("Response", (), {"status": 200, "headers": {}, "body": answer})()


def _source(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]
) -> tuple[Any, _Answers]:
    recorder = _Answers(answers)
    monkeypatch.setattr(provider, "request_with_retry", recorder)
    monkeypatch.setattr(equivalence, "request_with_retry", recorder)
    return provider.RepositoryProviderSource("owner/repo", "token"), recorder


def _compare(status: str, files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "total_commits": 0,
        "commits": [],
        "files": [] if files is None else files,
    }


_COMPARE_PATH = f"/repos/owner/repo/compare/{CANDIDATE}...{COMMIT}"
