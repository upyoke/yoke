"""Red member QA releases only a recorded correction excluded by its own pin."""

from types import SimpleNamespace

from runtime.api.domain.test_deployment_run_member_removal import (
    ITEM,
    RUN,
    _red_member,
    _still_member,
)
from runtime.api.fixtures.carried_release_candidate import (
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from yoke_core.domain.deployment_qa_failure_handoff import notify_member_qa_failure
from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_settlement import settle_subject
from yoke_core.domain.deployment_run_candidate_containment import (
    CandidateContainment,
    ContainmentVerdict,
    UNDETERMINED,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals


def _candidate(conn, tmp_path, monkeypatch, *, outside=True):
    requirement = _red_member(conn)
    repo, frozen, correction = release_repository(tmp_path, "failed QA")
    serve_repository(monkeypatch, repo)
    conn.execute(
        "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s", (frozen, RUN)
    )
    record_landing_receipt(
        conn, ITEM, branch="correction", tip=correction if outside else frozen
    )
    conn.commit()
    return requirement


def _handoff(conn):
    status = deployment_qa_stage_status(
        conn, run_id=RUN, stage_name="item-qa", member_item_id=ITEM
    )
    assert status["outcome"] == "blocked"
    return notify_member_qa_failure(
        conn, run_id=RUN, stage="item-qa", item_id=ITEM, status=status
    )


def test_excluded_correction_releases_member_and_retains_failure_history(
    test_db, tmp_path, monkeypatch
):
    requirement = _candidate(test_db, tmp_path, monkeypatch)
    bodies = []
    monkeypatch.setattr(
        "yoke_core.domain.deployment_member_removal_notice.push_member_notice",
        lambda conn, **kw: bodies.append(kw["body_for_route"]("holder")) or "sent",
    )
    assert _handoff(test_db).startswith("released:")
    assert not _still_member(test_db)
    (removal,) = membership_removals(test_db, RUN)
    assert removal["item_id"] == ITEM and "not contained" in removal["reason"]
    row = test_db.execute(
        "SELECT retracted_at,waived_at FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()
    assert row["retracted_at"] and row["waived_at"] is None
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s", (requirement,)
        ).fetchone()[0]
        == "fail"
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[0]
        == "release"
    )
    assert bodies and "item rides a later release" in bodies[0]
    assert "cancelled (not passed)" in bodies[0]


def test_correction_inside_pin_keeps_member(test_db, tmp_path, monkeypatch):
    _candidate(test_db, tmp_path, monkeypatch, outside=False)
    assert not _handoff(test_db).startswith("released:")
    assert _still_member(test_db)
    assert not membership_removals(test_db, RUN)


def test_unknown_containment_holds_and_reports_recovery(
    test_db, tmp_path, monkeypatch, capsys
):
    _candidate(test_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        CandidateContainment,
        "contains",
        lambda *_: ContainmentVerdict(
            UNDETERMINED,
            "repository_unavailable",
            "Restore repository access, then retry.",
        ),
    )
    assert not _handoff(test_db).startswith("released:")
    assert _still_member(test_db)
    assert not membership_removals(test_db, RUN)
    output = capsys.readouterr().out
    assert "member_candidate_containment_unproven" in output
    assert "repository_unavailable" in output and "Restore repository access" in output


def test_dispatch_does_not_keep_removed_member_in_waiting_roster(
    test_db, tmp_path, monkeypatch
):
    _candidate(test_db, tmp_path, monkeypatch)
    stage = pinned_stages(test_db, RUN)[-1]
    assert materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN) == (
        0,
        "",
    )
    assert not _still_member(test_db)


def test_failure_settlement_requests_continuation_after_removal(
    test_db, tmp_path, monkeypatch
):
    _candidate(test_db, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_auto_completion.continue_after_settlement",
        lambda conn, run_id, **kw: (
            calls.append(run_id) or SimpleNamespace(completed=True)
        ),
    )
    status = settle_subject(test_db, run_id=RUN, stage="item-qa", member=ITEM)
    assert status["outcome"] == "blocked"  # The original verdict is never rewritten.
    assert calls == [RUN] and not _still_member(test_db)


def test_shared_gate_keeps_excluded_red_member(test_db, tmp_path, monkeypatch, capsys):
    _candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        'UPDATE deployment_flows SET stages=replace(stages, \'"scope": "item"\', \'"scope": "run"\') WHERE id=(SELECT flow FROM deployment_runs WHERE id=%s)',
        (RUN,),
    )
    test_db.commit()
    # The failure notice may have loaded item status just before a boundary read.
    assert not notify_member_qa_failure(
        test_db,
        run_id=RUN,
        stage="item-qa",
        item_id=ITEM,
        status={
            "outcome": "blocked",
            "case_failures": [{"requirement_id": 1, "kind": "red"}],
        },
    ).startswith("released:")
    assert _still_member(test_db)
    assert "member_candidate_release_held" in capsys.readouterr().out


def test_a_new_landing_during_containment_is_not_removed(
    test_db, tmp_path, monkeypatch
):
    _candidate(test_db, tmp_path, monkeypatch)
    real = CandidateContainment.contains

    def moved(walker, sha):
        verdict = real(walker, sha)
        record_landing_receipt(test_db, ITEM, branch="correction", tip="f" * 40)
        return verdict

    monkeypatch.setattr(CandidateContainment, "contains", moved)
    assert not _handoff(test_db).startswith("released:")
    assert _still_member(test_db)
