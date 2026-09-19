"""Browser evidence is judged against the build it ran on, not SHA equality.

A capture taken against a deployed environment records that deployment's
own build identity. Demanding that identity BE one of the item's landing
commits passes only a release of exactly that item, and never passes an
item that changed no source at all: no build will ever report its landing
as its own identity. The question the gate means is whether the build
already carries the landing, so these exercise real git histories rather
than a stubbed comparison.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import deployment_run_carried_work_source
from yoke_core.domain.qa_browser_freshness_check import (
    _collect_stale_browser_requirements,
)
from yoke_core.domain.qa_gate_definitions import LatestCodeRef


@pytest.fixture
def evidence_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _deployed_history(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A trunk carrying the landing, a later build, and a build beside it."""
    repo = tmp_path / "evidence-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "app.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "Baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "app.txt").write_text("landed\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land the item")
    landing = _git(repo, "rev-parse", "HEAD")
    (repo / "app.txt").write_text("shipped later\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land a later neighbour")
    served = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "separate-line", baseline)
    (repo / "app.txt").write_text("separate\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Build from a separate line")
    without_landing = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return repo, landing, served, without_landing


def _seed_browser_evidence(conn, *, item_id: int, captured_sha: str) -> None:
    """One blocking Browser case whose latest pass ran on ``captured_sha``."""
    insert_item(conn, id=item_id, workflow_id="dash", status="reviewing-implementation")
    requirement = insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="plan_case",
        method_id="browser-inspection",
        qa_phase="verification",
    )
    insert_qa_run(
        conn,
        qa_requirement_id=int(requirement["id"]),
        performed_by="browser_substrate",
        qa_kind="plan_case",
        verdict="pass",
        raw_result=json.dumps(
            {
                "base_url": "https://app.example.com",
                "freshness_validated": True,
                "code_identity": {"branch": "main", "sha": captured_sha},
            }
        ),
    )


def _stale_rows(db_path: str, *, item_id: int, landing: str):
    """Run the gate's freshness collection the way a checkout-less host does.

    ``LatestCodeRef`` carries no timestamp here on purpose: that is exactly
    what a control plane with no checkout of the project resolves, and it is
    the state in which the comparison used to degrade to SHA equality.
    """
    conn = connect_test_db(db_path)
    try:
        return _collect_stale_browser_requirements(
            conn,
            where="r.item_id = %s",
            params=(item_id,),
            latest_code=LatestCodeRef(sha=landing, accepted_shas=(landing,)),
            qa_phase="verification",
            item_id=item_id,
        )
    finally:
        conn.close()


@pytest.fixture
def repo_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, landing, served, without_landing = _deployed_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    return repo, landing, served, without_landing


def test_capture_against_a_build_containing_the_landing_is_accepted(
    evidence_db_path: str, repo_history
):
    _repo, landing, served, _fork = repo_history
    conn = connect_test_db(evidence_db_path)
    try:
        _seed_browser_evidence(conn, item_id=4101, captured_sha=served)
    finally:
        conn.close()

    assert _stale_rows(evidence_db_path, item_id=4101, landing=landing) == []


def test_capture_recorded_at_the_landing_itself_is_accepted(
    evidence_db_path: str, repo_history
):
    _repo, landing, _served, _fork = repo_history
    conn = connect_test_db(evidence_db_path)
    try:
        _seed_browser_evidence(conn, item_id=4102, captured_sha=landing)
    finally:
        conn.close()

    assert _stale_rows(evidence_db_path, item_id=4102, landing=landing) == []


def test_capture_against_a_build_lacking_the_landing_is_refused(
    evidence_db_path: str, repo_history
):
    _repo, landing, _served, without_landing = repo_history
    conn = connect_test_db(evidence_db_path)
    try:
        _seed_browser_evidence(conn, item_id=4103, captured_sha=without_landing)
    finally:
        conn.close()

    stale = _stale_rows(evidence_db_path, item_id=4103, landing=landing)
    assert [row[3] for row in stale] == [without_landing]
    # A definite exclusion is refused on its own terms, with no unreadable
    # reason attached: the build really does not carry the landing.
    assert [row[4] for row in stale] == [""]


def test_a_build_no_source_can_place_refuses_with_that_reason(
    evidence_db_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _repo, landing, served, _fork = _deployed_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )
    conn = connect_test_db(evidence_db_path)
    try:
        _seed_browser_evidence(conn, item_id=4104, captured_sha=served)
    finally:
        conn.close()

    stale = _stale_rows(evidence_db_path, item_id=4104, landing=landing)
    assert len(stale) == 1
    # Re-running the case would record the same revision forever, so the
    # refusal names the source that could not answer instead.
    assert "could not be determined" in stale[0][4]
