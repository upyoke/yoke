"""Preparation refreshes containment after a landing races its preview."""

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.bound_source_release import two_project_release
from runtime.api.fixtures.carried_release_candidate import (
    git,
    item_ref,
    record_landing_receipt,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import deployment_run_bound_source_prepare as preparation
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_contained_items import (
    CandidateContainmentRefusal,
    attest_candidate_containment,
    candidate_containment_basis,
    record_attested_candidate_containment,
)


def _setup(conn, tmp_path, monkeypatch):
    release = two_project_release(conn, tmp_path, monkeypatch)
    record_bound_sources(conn, "run-candidate")
    attestation = attest_candidate_containment(
        candidate_containment_basis(conn, "run-candidate"),
        lambda slug: str(
            release["carrier_repo"] if slug == "yoke" else release["consumer_repo"]
        ),
        run_id="run-recovery",
    )
    record_attested_candidate_containment(conn, "run-candidate", attestation)
    conn.commit()
    git(release["consumer_repo"], "commit", "--allow-empty", "-m", "Advance source")
    return release


def _run_state(conn):
    row = conn.execute(
        "SELECT bound_sources,carried_work,candidate_containment FROM deployment_runs "
        "WHERE id='run-candidate'"
    ).fetchone()
    members = conn.execute(
        "SELECT item_id,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-candidate' ORDER BY item_id"
    ).fetchall()
    return tuple(row), [tuple(member) for member in members]


@pytest.mark.parametrize("landings", [1, 2, 3])
def test_landing_between_preview_and_apply_retries_with_rolled_back_state(
    test_db, tmp_path, monkeypatch, landings
):
    release = _setup(test_db, tmp_path, monkeypatch)
    original = _run_state(test_db)
    preview = preparation.preview_bound_source_composition
    previews = []

    def racing_preview(conn, *args):
        # Every new attempt must start with the original pins and membership.
        assert _run_state(conn) == original
        result = preview(conn, *args)
        previews.append(result)
        if len(previews) <= landings:
            # Commit an actual landing after the preview but before its locks.
            # The primary candidate remains fixed; this later commit is outside it.
            git(release["carrier_repo"], "commit", "--allow-empty", "-m", "Land work")
            tip = git(release["carrier_repo"], "rev-parse", "HEAD")
            item_id = 9800 + len(previews)
            insert_item(
                conn,
                id=item_id,
                project_sequence=item_id,
                workflow_id="blitz",
                status="done",
                deployment_flow="carrier-release-flow",
            )
            record_landing_receipt(
                conn, item_id, branch=item_ref(conn, item_id), tip=tip
            )
            conn.execute(
                "UPDATE items SET merged_at=%s WHERE id=%s", (utc_now(), item_id)
            )
            conn.execute(
                "INSERT INTO item_status_transitions (item_id,from_status,to_status,created_at) "
                "VALUES (%s,'release','done',%s)",
                (item_id, utc_now()),
            )
            conn.commit()
        return result

    monkeypatch.setattr(preparation, "preview_bound_source_composition", racing_preview)
    if landings == 3:
        with pytest.raises(CandidateContainmentRefusal) as refused:
            preparation.prepare_bound_sources(
                test_db, "run-candidate", "hosted-release"
            )
        assert refused.value.code == "candidate_containment_attestation_stale"
        assert "re-drive run-candidate" in str(refused.value)
        assert _run_state(test_db) == original
        assert len(previews) == 3
    else:
        result = preparation.prepare_bound_sources(
            test_db, "run-candidate", "hosted-release"
        )
        test_db.commit()
        assert len(previews) == landings + 1
        source = result["bound_sources"]["projects"][0]
        assert source["consumed_by"] == "hosted-release"
        assert len(source["rebindings"]) == 1
        assert source["commit_sha"] == git(
            release["consumer_repo"], "rev-parse", "HEAD"
        )
        snapshot = json.loads(_run_state(test_db)[0][2])
        assert {answer["id"] for answer in snapshot["answers"]} >= {
            9800 + index for index in range(1, landings + 1)
        }


def test_other_containment_refusal_is_not_retried(monkeypatch):
    attempts = []

    def refuse(*args):
        attempts.append(args)
        raise CandidateContainmentRefusal(
            "source_unverified", "missing evidence", "repair source"
        )

    monkeypatch.setattr(preparation, "_prepare_bound_sources", refuse)
    with pytest.raises(CandidateContainmentRefusal, match="source_unverified"):
        preparation.prepare_bound_sources(object(), "run-candidate", "hosted-release")
    assert len(attempts) == 1
