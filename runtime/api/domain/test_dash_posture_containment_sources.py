# ruff: noqa: F811
"""Containment answers by content, and from whichever source can answer.

Two facts the ancestry-only, single-source check could not deliver: a lane
whose commits reached the base under other identities is contained in
content, and a source that cannot answer is not the end of the question.
Both are exercised against real git histories rather than a stubbed
comparison, because the answer is exactly what git computes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.domain.test_dash_posture_deployment_containment import (  # noqa: F401
    _bind_lane_head,
    _deploy_posture_item,
    _git,
    dash_db_path,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_run_carried_work_source as sources
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    UNDETERMINED,
    candidate_contains_commit,
)


def _replayed_lane(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A lane whose content reached the trunk under different commit ids.

    This is the shape a companion item's landing produces: the lane's own
    commit is on no trunk ancestry path, its file is already in the trunk
    with identical content, and the trunk has moved on since.
    """
    repo = tmp_path / "replayed-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    baseline = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "-b", "lane", baseline)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "Add the feature on the lane")
    lane_head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "main")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "Land the same feature under a companion item")
    carrier = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land a later neighbour")
    tip = _git(repo, "rev-parse", "HEAD")
    return repo, lane_head, carrier, tip


def _empty_repository(tmp_path: Path) -> Path:
    """A checkout that holds neither commit, so it cannot answer at all."""
    repo = tmp_path / "unrelated-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


class _StubSource:
    """One source with a scripted answer, standing in for the provider."""

    origin = "repository_provider"

    def __init__(self, *, contains: bool | None) -> None:
        self._contains = contains

    def resolve_commit(self, ref: str) -> str:
        return ref

    def contains_commit(self, candidate: str, commit: str) -> bool | None:
        return self._contains

    def adds_nothing(self, candidate: str, commit: str) -> bool | None:
        return None


def test_the_gate_closes_a_lane_whose_content_landed_under_other_commits(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The refusal a companion item's landing used to produce."""
    repo, lane_head, carrier, tip = _replayed_lane(tmp_path)
    monkeypatch.setattr(
        sources, "checkout_for_project_id", lambda _project_id: repo
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2401, merge_sha=carrier, lineage=tip)
        # The lane head is on no ancestry path to the deployed tip, and the
        # deployed tip already holds every line it carries.
        _bind_lane_head(conn, item_id=2401, commit_sha=lane_head)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    assert evaluate(item_id=2401, target_status="done", db_path=dash_db_path) is None


def test_a_lane_still_carrying_work_is_refused_on_content_too(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, _lane_head, carrier, tip = _replayed_lane(tmp_path)
    _git(repo, "checkout", "-q", "lane")
    (repo / "unlanded.txt").write_text("still mine\n", encoding="utf-8")
    _git(repo, "add", "unlanded.txt")
    _git(repo, "commit", "-m", "Work that never reached the trunk")
    carrying_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    monkeypatch.setattr(
        sources, "checkout_for_project_id", lambda _project_id: repo
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2402, merge_sha=carrier, lineage=tip)
        _bind_lane_head(conn, item_id=2402, commit_sha=carrying_head)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    refusal = evaluate(item_id=2402, target_status="done", db_path=dash_db_path)
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"


def test_a_checkout_that_cannot_answer_falls_through_to_the_next_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = _empty_repository(tmp_path)
    monkeypatch.setattr(
        sources, "checkout_for_project_id", lambda _project_id: repo
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_carried_work_repository."
        "open_repository_provider_source",
        lambda _conn, _project_id: _StubSource(contains=True),
    )

    verdict = candidate_contains_commit(
        None, 1, candidate_lineage="a" * 40, commit_sha="b" * 40,
    )

    assert verdict.state == CONTAINED
    assert verdict.source == "repository_provider"


def test_an_unanswerable_comparison_names_every_source_that_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = _empty_repository(tmp_path)
    monkeypatch.setattr(
        sources, "checkout_for_project_id", lambda _project_id: repo
    )

    def _refuse(_conn, _project_id):
        raise sources.CarriedWorkSourceUnavailable(
            "project_source_unavailable", "Authorize the binding."
        )

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_carried_work_repository."
        "open_repository_provider_source",
        _refuse,
    )

    verdict = candidate_contains_commit(
        None, 1, candidate_lineage="a" * 40, commit_sha="b" * 40,
    )

    assert verdict.state == UNDETERMINED
    # Both the checkout that could not see the commits and the binding that
    # could not be opened are named, because each is separately fixable.
    assert "containment_commit_unreachable" in verdict.reason
    assert "project_source_unavailable" in verdict.reason
