"""Containment over the repository provider: cheap ancestry, honest content.

A control plane with no checkout answers both containment questions from the
project's own binding. Ancestry is read with the candidate as the comparison
base — the direction whose listing is empty when the answer is yes — and
content is read from the paths the commit changed, which is the only way a
reader that cannot merge trees can tell "already present" from "missing".
"""

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


@pytest.mark.parametrize(
    ("status", "contained"),
    [("behind", True), ("identical", True), ("ahead", False), ("diverged", False)],
)
def test_ancestry_is_read_from_the_candidate_side(
    monkeypatch: pytest.MonkeyPatch, status: str, contained: bool
):
    source, recorder = _source(monkeypatch, {_COMPARE_PATH: _compare(status)})

    assert source.contains_commit(CANDIDATE, COMMIT) is contained
    # The candidate is the base: asking the other way round returns the whole
    # release and every file patch in it for the same one-bit answer.
    assert recorder.paths == [_COMPARE_PATH]


def test_a_commit_changing_nothing_adds_nothing(monkeypatch: pytest.MonkeyPatch):
    source, _ = _source(monkeypatch, {_COMPARE_PATH: _compare("diverged")})

    assert source.adds_nothing(CANDIDATE, COMMIT) is True


def test_content_already_on_the_candidate_adds_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    """The replayed lane: its changes are in the candidate under other shas."""
    source, recorder = _source(
        monkeypatch,
        {
            _COMPARE_PATH: _compare(
                "diverged",
                [{"filename": "feature.py", "status": "modified", "sha": "f" * 40}],
            ),
            "/repos/owner/repo/contents/feature.py": {"sha": "f" * 40},
        },
    )

    assert source.adds_nothing(CANDIDATE, COMMIT) is True
    assert "/repos/owner/repo/contents/feature.py" in recorder.paths


def test_content_the_candidate_lacks_still_adds_something(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _ = _source(
        monkeypatch,
        {
            _COMPARE_PATH: _compare(
                "diverged",
                [{"filename": "feature.py", "status": "modified", "sha": "f" * 40}],
            ),
            "/repos/owner/repo/contents/feature.py": {"sha": "0" * 40},
        },
    )

    assert source.adds_nothing(CANDIDATE, COMMIT) is False


def test_a_deletion_the_candidate_already_made_adds_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _ = _source(
        monkeypatch,
        {
            _COMPARE_PATH: _compare(
                "diverged", [{"filename": "gone.py", "status": "removed", "sha": ""}]
            ),
            "/repos/owner/repo/contents/gone.py": RestNotFoundError(
                "no content", status=404
            ),
        },
    )

    assert source.adds_nothing(CANDIDATE, COMMIT) is True


def test_a_deletion_the_candidate_has_not_made_adds_something(
    monkeypatch: pytest.MonkeyPatch,
):
    source, _ = _source(
        monkeypatch,
        {
            _COMPARE_PATH: _compare(
                "diverged", [{"filename": "gone.py", "status": "removed", "sha": ""}]
            ),
            "/repos/owner/repo/contents/gone.py": {"sha": "9" * 40},
        },
    )

    assert source.adds_nothing(CANDIDATE, COMMIT) is False


def test_a_listing_past_the_budget_is_unread_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
):
    files = [
        {"filename": f"file{index}.py", "status": "modified", "sha": "f" * 40}
        for index in range(equivalence.COMPARED_PATH_BUDGET + 1)
    ]
    source, recorder = _source(monkeypatch, {_COMPARE_PATH: _compare("diverged", files)})

    assert source.adds_nothing(CANDIDATE, COMMIT) is None
    # Nothing was priced, so nothing was read beyond the comparison itself.
    assert recorder.paths == [_COMPARE_PATH]


def test_both_containment_questions_share_one_comparison_read(
    monkeypatch: pytest.MonkeyPatch,
):
    source, recorder = _source(monkeypatch, {_COMPARE_PATH: _compare("diverged")})

    assert source.contains_commit(CANDIDATE, COMMIT) is False
    assert source.adds_nothing(CANDIDATE, COMMIT) is True
    assert recorder.paths == [_COMPARE_PATH]
