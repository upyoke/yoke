"""A release cut over a live one composes nothing for the member that run holds.

The carried range is commit arithmetic: it names every delivery-ready landing
between the previous succeeded release and this candidate, including the
landing a live release is still mid-delivery on. Composing that landing again
puts two runs on one obligation, and where the holder's flow is not this run's,
the final-member completion-authority refusal then rejects the whole creation
over a member this candidate was only ever carrying as ancestor code.

So the exclusion has to hold in both places, and the refusal it narrows has to
survive it: an unheld member on another flow is still refused by name, and a
member whose only holder ended is composed like any other carried landing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_member_run_coverage import (
    unclosable_final_member_refusal,
)
from yoke_core.domain.deployment_run_carried_membership import (
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.flow_create import cmd_create


#: The candidate's own flow, and the flow the held item selects instead.
CARRIER_FLOW = "held-member-carrier-flow"
HOLDER_FLOW = "held-member-holder-flow"
RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)
LANDED_ITEM_ID = 9731


def _final_delivery(conn: Any, *run_ids: str) -> None:
    """Make each run the persistent-tier release that owes its members done.

    The prior release needs the same target environment as the candidate: the
    carried range's baseline is the last succeeded run of THAT environment, so
    tiering only the candidate would leave it with no range at all.
    """
    environment = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for run_id in run_ids:
        conn.execute(
            "UPDATE deployment_runs SET target_tier='persistent',"
            "target_environment_id=%s WHERE id=%s",
            (environment, run_id),
        )
    conn.commit()


def _carried_landing(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item_flow: str,
) -> str:
    """One delivery-ready landing inside the new candidate's carried range."""
    insert_item(
        conn,
        id=LANDED_ITEM_ID,
        project_sequence=LANDED_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=item_flow,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, LANDED_ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_landing_receipt(conn, LANDED_ITEM_ID, branch=ref, tip=landing)
    stage_environment(conn)
    for flow in (CARRIER_FLOW, HOLDER_FLOW):
        cmd_create(
            conn, flow, "yoke", flow, "", RELEASE_STAGES, status="disabled"
        )
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=CARRIER_FLOW
    )
    insert_run(
        conn, "run-candidate", lineage=landing, status="created", flow=CARRIER_FLOW
    )
    _final_delivery(conn, "run-previous", "run-candidate")
    return ref


def _holder(conn: Any, run_id: str, *, status: str, flow: str = HOLDER_FLOW) -> None:
    """A second run that named this item and pinned the same landing."""
    lineage = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    insert_run(conn, run_id, lineage=lineage, status=status, flow=flow)
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES (%s,%s,'2026-09-14T00:30:00Z')",
        (run_id, LANDED_ITEM_ID),
    )
    conn.commit()


def _members(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate' "
        "ORDER BY item_id"
    ).fetchall()
    return [int(dict(row)["item_id"]) for row in rows]


def test_a_landing_a_live_run_holds_is_skipped_rather_than_refused(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported failure: creation rejected over a member of a live run."""
    ref = _carried_landing(
        test_db, tmp_path, monkeypatch, item_flow=HOLDER_FLOW
    )
    _holder(test_db, "run-live", status="executing")
    # Proves the carried range really does propose it, so the exclusion below
    # is what leaves it out rather than an accident of the comparison.
    carried = derive_carried_work(test_db, "run-candidate")
    assert [entry["item_id"] for entry in carried["items"]] == [LANDED_ITEM_ID]

    custody = candidate_custody(test_db, "run-candidate")
    ok, message = cmd_validate_composition("run-candidate")

    assert custody.held_ids == frozenset({LANDED_ITEM_ID})
    assert custody.enrollable == ()
    assert ok is True, message
    assert _members(test_db) == []
    assert "Skipped 1 delivery-ready item(s)" in message
    assert f"{ref} held by run-live (executing)" in message
    assert "no authority to close" not in message


def test_an_unheld_member_on_another_flow_is_still_refused(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrowing must not retire the refusal it narrows."""
    ref = _carried_landing(
        test_db, tmp_path, monkeypatch, item_flow=HOLDER_FLOW
    )

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is False
    assert f"{ref} selects completion flow '{HOLDER_FLOW}'" in message


def test_a_landing_only_a_terminal_run_named_is_composed_normally(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled run holds nothing, so its landing is this release's to take."""
    ref = _carried_landing(
        test_db, tmp_path, monkeypatch, item_flow=CARRIER_FLOW
    )
    _holder(test_db, "run-cancelled", status="cancelled", flow=CARRIER_FLOW)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (ref,)
    assert _members(test_db) == [LANDED_ITEM_ID]
    assert candidate_custody(test_db, "run-candidate").held_ids == frozenset()


def test_a_held_member_attached_by_hand_passes_the_authority_check(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final-member check reads custody too, or the skip is undone at freeze.

    Enrollment leaves the held landing out, but an operator can still attach
    it. The holder owes the close, so this run is not the one refusing.
    """
    _carried_landing(test_db, tmp_path, monkeypatch, item_flow=HOLDER_FLOW)
    _holder(test_db, "run-live", status="executing")
    cmd_add_item("run-candidate", LANDED_ITEM_ID)

    assert _members(test_db) == [LANDED_ITEM_ID]
    assert unclosable_final_member_refusal(test_db, "run-candidate") is None
