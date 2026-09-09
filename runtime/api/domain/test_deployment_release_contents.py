"""A deployment approval snapshot answers what the release actually carries.

Run membership answers which items the pipeline owns; an environment run owns
none while still shipping every change merged since the last release. The
answer is derived once, when the request is created, and frozen into the
snapshot — deriving reads git, so re-running it on every pending-gate
evaluation would pay repeatedly for a fact the snapshot already holds.
"""

from __future__ import annotations

from runtime.api.deployment_stage_approval_fixture import seed_stage_approval
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)


def test_release_contents_are_derived_once_and_change_nothing(
    test_db,
    monkeypatch,
):
    """The snapshot answers what ships without deriving on every evaluation.

    Deriving reads git, so re-running it each time a pending gate is
    re-evaluated would pay for a fact the snapshot already froze. Membership
    and item lifecycle are untouched either way: carried work is a statement
    about source changes, never a claim on which items the pipeline owns.
    """
    seeded = seed_stage_approval(test_db)
    derivations = []
    import yoke_core.domain.deployment_run_carried_work as carried_work

    real = carried_work.derive_carried_work

    def counted(conn, run_id, **kwargs):
        derivations.append(run_id)
        return real(conn, run_id, **kwargs)

    monkeypatch.setattr(carried_work, "derive_carried_work", counted)

    def membership():
        return [
            int(row["item_id"])
            for row in test_db.execute(
                "SELECT item_id FROM deployment_run_items "
                "WHERE run_id=%s ORDER BY item_id",
                (seeded["run_id"],),
            ).fetchall()
        ]

    def statuses():
        return [
            (int(row["id"]), str(row["status"]))
            for row in test_db.execute(
                "SELECT id, status FROM items ORDER BY id"
            ).fetchall()
        ]

    membership_before = membership()
    statuses_before = statuses()

    first = evaluate_deployment_stage_approval(
        test_db,
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    for _ in range(3):
        repeated = evaluate_deployment_stage_approval(
            test_db,
            run_id=seeded["run_id"],
            originator_actor_id=seeded["originator"],
        )
        assert repeated.request_id == first.request_id

    assert derivations == [seeded["run_id"]]
    assert membership() == membership_before
    assert statuses() == statuses_before
    # Derivation is a read: the completion record is still unwritten, so the
    # pre-approval snapshot has not stood in for it.
    assert (
        test_db.execute(
            "SELECT carried_work FROM deployment_runs WHERE id=%s",
            (seeded["run_id"],),
        ).fetchone()[0]
        is None
    )


def test_a_stored_snapshot_survives_and_a_new_lineage_does_not(test_db):
    """Adding a fact to new snapshots must not disturb the pending ones.

    A request already answering for a run keeps its exact stored context, and
    a run whose release lineage moves still gets a fresh request, because the
    lineage is one of the fields the staleness comparison reads.
    """
    seeded = seed_stage_approval(test_db)
    first = evaluate_deployment_stage_approval(
        test_db,
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    stored = test_db.execute(
        "SELECT subject_context FROM decision_requests WHERE id=%s",
        (first.request_id,),
    ).fetchone()[0]

    repeated = evaluate_deployment_stage_approval(
        test_db,
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    assert repeated.request_id == first.request_id
    assert (
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s",
            (first.request_id,),
        ).fetchone()[0]
        == stored
    )

    test_db.execute(
        "UPDATE deployment_runs SET release_lineage='moved-lineage' WHERE id=%s",
        (seeded["run_id"],),
    )
    test_db.commit()
    moved = evaluate_deployment_stage_approval(
        test_db,
        run_id=seeded["run_id"],
        originator_actor_id=seeded["originator"],
    )
    assert moved.request_id != first.request_id
    assert (
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s",
            (first.request_id,),
        ).fetchone()[0]
        == stored
    )
