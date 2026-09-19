# ruff: noqa: F811
"""The lane answers containment for a control plane that cannot look.

A host serving an https project holds no checkout of it, so there are real
containment questions its repository reader can only call undetermined — and
an undetermined containment refuses a correctly delivered item at ``done``.
The client that merged the item was standing in a checkout and could answer
exactly, so it attests the verdict with its terminal transition.

Two properties are what make that safe, and both are pinned here: the relay
is consulted only where the host's own sources came back undetermined, and
only for the exact pair of commits it names.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.api.domain.test_dash_posture_deployment_containment import (  # noqa: F401
    _deploy_posture_item,
    _git,
    dash_db_path,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_run_carried_work_source as sources
from yoke_core.domain.lane_containment_attestation import (
    CONTAINED,
    NOT_CONTAINED,
    lane_containment,
)
from yoke_core.domain.relayed_containment_attestation import (
    relayed_attestations_bound,
)


CANDIDATE = "c" * 40
MERGE = "b" * 40


def _blind_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A host with no checkout of the project and no readable binding."""
    empty = tmp_path / "no-checkout"
    empty.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(empty)],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setattr(sources, "checkout_for_project_id", lambda _pid: empty)

    def _refuse(_conn, _project_id):
        raise sources.CarriedWorkSourceUnavailable(
            "project_source_unavailable", "Authorize the binding."
        )

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_carried_work_repository."
        "open_repository_provider_source",
        _refuse,
    )


def _attestation(state: str, *, candidate: str = CANDIDATE, commit: str = MERGE):
    return {
        "candidate_ref": candidate,
        "candidate_sha": candidate,
        "commit_sha": commit,
        "state": state,
        "method": "lane_adds_nothing",
        "source": "lane_checkout",
    }


def _run_id(item_id: int) -> str:
    return f"run-dash-{item_id}"


def test_a_lane_verdict_closes_an_item_the_host_cannot_answer_for(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _blind_host(monkeypatch, tmp_path)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2501, merge_sha=MERGE, lineage=CANDIDATE)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    with relayed_attestations_bound([_attestation(CONTAINED)]):
        assert evaluate(
            item_id=2501, target_status="done", db_path=dash_db_path
        ) is None


def test_the_relayed_evidence_outlives_the_transition_that_carried_it(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Whoever asks later must be able to see what was compared, and how."""
    _blind_host(monkeypatch, tmp_path)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2502, merge_sha=MERGE, lineage=CANDIDATE)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    with relayed_attestations_bound([_attestation(CONTAINED)]):
        evaluate(item_id=2502, target_status="done", db_path=dash_db_path)

    conn = connect_test_db(dash_db_path)
    try:
        row = conn.execute(
            "SELECT containment_attestation FROM deployment_run_items "
            "WHERE run_id = %s AND item_id = %s",
            (_run_id(2502), 2502),
        ).fetchone()
    finally:
        conn.close()
    recorded = json.loads(row["containment_attestation"])
    assert recorded["candidate_sha"] == CANDIDATE
    assert recorded["commit_sha"] == MERGE
    assert recorded["method"] == "lane_adds_nothing"
    assert recorded["recorded_at"]


def test_an_attestation_about_another_release_is_ignored(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A verdict taken against a different candidate answers nothing here."""
    _blind_host(monkeypatch, tmp_path)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2503, merge_sha=MERGE, lineage=CANDIDATE)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    with relayed_attestations_bound(
        [_attestation(CONTAINED, candidate="d" * 40)]
    ):
        refusal = evaluate(
            item_id=2503, target_status="done", db_path=dash_db_path
        )
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_CONTAINMENT_UNDETERMINED"


def test_a_lane_verdict_never_overrides_a_host_that_can_see(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The host answered for itself, so the relay is not consulted at all."""
    from runtime.api.domain.test_dash_posture_deployment_containment import (
        _release_history,
    )

    repo, merge, _tip, fork = _release_history(tmp_path)
    monkeypatch.setattr(sources, "checkout_for_project_id", lambda _pid: repo)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2504, merge_sha=merge, lineage=fork)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    with relayed_attestations_bound(
        [_attestation(CONTAINED, candidate=fork, commit=merge)]
    ):
        refusal = evaluate(
            item_id=2504, target_status="done", db_path=dash_db_path
        )
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"


def test_the_lane_answers_both_containment_questions_from_its_checkout(
    tmp_path: Path,
):
    """What the client actually attests, computed against a real history."""
    repo = tmp_path / "lane-project"
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
    (repo / "release.txt").write_text("item\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land the item")
    merge = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "elsewhere", baseline)
    (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-m", "Work the trunk never took")
    unlanded = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    carried = lane_containment(str(repo), candidate=merge, commit_sha=merge)
    assert carried is not None
    assert carried["state"] == CONTAINED
    assert carried["method"] == "ancestry"
    assert carried["candidate_sha"] == merge

    absent = lane_containment(str(repo), candidate=merge, commit_sha=unlanded)
    assert absent is not None
    assert absent["state"] == NOT_CONTAINED
    assert absent["method"] == "lane_adds_nothing"


def test_a_lane_that_never_fetched_the_candidate_attests_nothing(
    tmp_path: Path,
):
    """An unanswered question relays nothing rather than relaying a guess."""
    repo = tmp_path / "shallow-lane"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert lane_containment(str(repo), candidate=CANDIDATE, commit_sha=MERGE) is None


def test_a_gate_refusal_carries_what_to_do_about_it():
    """A diagnosed refusal is two facts, and only relaying one strands a reader.

    The containment refusal names a provider code. A rate limit, a revoked
    permission and a 502 all arrive under that one code and need three
    different actions, so the step that clears it has to travel with it.
    """
    from yoke_core.domain.handlers.items_scalar import gate_failure_message

    refused = {
        "success": False,
        "error_code": "GATE_DASH_DEPLOYMENT_CONTAINMENT_UNDETERMINED",
        "error": "Whether the deployed candidate contains the current work "
        "could not be determined (repository_head_unpublished).",
        "remediation_hint": "Publish or land the lane, then retry.",
    }

    message = gate_failure_message(refused, "lifecycle transition failed")

    assert "repository_head_unpublished" in message
    assert "Publish or land the lane" in message
    assert gate_failure_message({}, "fallback") == "fallback"


def test_a_lane_head_a_rebase_orphaned_is_not_undeployed_work(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The pointer, not the work, is what went missing.

    ``item_worktrees.commit_sha`` tracks the lane, and a rebase rewrites the
    lane — so the commit it named stops existing anywhere and no source can
    place it. Read literally that is an undetermined containment and the gate
    refuses, stranding an item whose merge the release demonstrably carries.
    """
    from runtime.api.domain.test_dash_posture_deployment_containment import (
        _bind_lane_head,
        _release_history,
    )

    repo, merge, tip, _fork = _release_history(tmp_path)
    monkeypatch.setattr(sources, "checkout_for_project_id", lambda _pid: repo)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2601, merge_sha=merge, lineage=tip)
        # A commit no source holds: the rewrite left nothing behind.
        _bind_lane_head(conn, item_id=2601, commit_sha="e" * 40)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    assert evaluate(
        item_id=2601, target_status="done", db_path=dash_db_path
    ) is None


def test_an_unplaceable_head_still_refuses_when_the_merge_is_unaccounted_for(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Nothing has established that this lane's work shipped at all."""
    from runtime.api.domain.test_dash_posture_deployment_containment import (
        _bind_lane_head,
        _release_history,
    )

    repo, merge, _tip, fork = _release_history(tmp_path)
    monkeypatch.setattr(sources, "checkout_for_project_id", lambda _pid: repo)
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2602, merge_sha=merge, lineage=fork)
        _bind_lane_head(conn, item_id=2602, commit_sha="e" * 40)
    finally:
        conn.close()

    from yoke_core.domain.dash_posture_gate import evaluate

    refusal = evaluate(item_id=2602, target_status="done", db_path=dash_db_path)
    assert refusal is not None
