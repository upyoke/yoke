"""Superseding an admitted copy names the intake row, and that exit is open.

Supersession is run-local: it discharges one frozen copy and never touches
the item requirement the copy was frozen from. That is deliberate -- the
intake row is a real outstanding obligation and discharging it from here
would drop it forever -- but leaving it unsaid is how a correction failed to
stick, because the next release admitted a fresh copy of the same defective
body and asked the same owner to run the same case.

Saying it is only half a fix, and the dangerous half to ship alone. The
amendment the receipt names runs through
:func:`qa_admitted_case_reconciliation.admitted_copies_in_flight`, which
selected admitted copies on ``waived_at`` alone. The copy the operator had
just superseded therefore still counted as in flight, was reported
unreachable because it carries a determinate ``fail``, and refused the
amendment -- offering, as its recovery, the supersession that had just
happened. These walk that command end to end on the exact case the receipt
is about rather than asserting its wording, because wording is what passes
while an exit stays shut.
"""

from __future__ import annotations

import json

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    deliver_with_failing_admitted_copy,
    intake_requirement,
)
from yoke_core.domain.qa_admitted_case_reconciliation import (
    ADMITTED_COPY_IN_FLIGHT_CODE,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_supersession import supersede_requirement

#: The shape the worked defect had: routes relative to a bare origin that
#: serves the marketing site, so every navigate landed off the workbench.
CORRECTED_CONFIG = {
    "steps": [
        {"action": "navigate", "route": "/workbench/releases/current"},
        {"action": "screenshot", "capture": True},
    ]
}


def _method_config(conn, requirement_id: int):
    stored = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    return json.loads(stored) if isinstance(stored, str) else stored


def _supersede(conn, *, broken_id: int, corrected_id: int) -> dict:
    return supersede_requirement(
        conn,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="routes were relative to the bare origin; corrected case passed",
        source="operator",
    )


def test_receipt_names_the_intake_row_and_the_command_that_corrects_it(
    test_db,
) -> None:
    item_id = 2350
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-names-source", corrected=True
    )

    receipt = _supersede(test_db, broken_id=broken_id, corrected_id=corrected_id)

    assert receipt["admitted_from_requirement_id"] == intake_id
    notice = receipt["next_admission_notice"]
    assert str(intake_id) in notice
    assert str(broken_id) in notice
    assert f"--requirement-id {intake_id}" in notice
    assert "yoke qa requirement update" in notice


def test_the_correction_the_receipt_names_actually_runs(test_db) -> None:
    """The reachability proof: execute the named command, do not read it.

    This is the test that would have failed had the receipt shipped alone.
    The run is still executing and the superseded copy still carries its
    ``fail``, which is exactly the state the notice is printed in.
    """
    item_id = 2351
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-correction-runs", corrected=True
    )
    receipt = _supersede(test_db, broken_id=broken_id, corrected_id=corrected_id)
    assert receipt["admitted_from_requirement_id"] == intake_id

    outcome = apply_requirement_update(
        test_db, intake_id, "method_config", json.dumps(CORRECTED_CONFIG)
    )

    assert outcome.ok, f"{outcome.error_code}: {outcome.message}"
    assert _method_config(test_db, intake_id)["steps"][0]["route"] == (
        "/workbench/releases/current"
    )
    # The discharged copy is left exactly as it was: the correction reaches
    # the source the next release reads, never the frozen acceptance record.
    assert _method_config(test_db, broken_id)["steps"][0]["route"] == (
        "/releases/current"
    )


def test_an_undischarged_failing_copy_still_refuses_the_correction(test_db) -> None:
    """The guard that had to survive opening the exit.

    A copy nobody has discharged is still owed an answer on a live run, so
    amending its source underneath it would leave that run certifying a body
    the item has already retracted. Only the discharge changes this.
    """
    item_id = 2352
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-still-owed", corrected=False
    )

    outcome = apply_requirement_update(
        test_db, intake_id, "method_config", json.dumps(CORRECTED_CONFIG)
    )

    assert not outcome.ok
    assert outcome.error_code == ADMITTED_COPY_IN_FLIGHT_CODE
    assert str(broken_id) in outcome.message
    assert _method_config(test_db, intake_id)["steps"][0]["route"] == (
        "/releases/current"
    )


def test_a_run_bound_case_that_is_no_admitted_copy_names_no_upstream(
    test_db,
) -> None:
    """A plan-backed run case was never copied from anything.

    Its ``plan_case_key`` is its plan's own, so there is no intake row to
    name and none is invented.
    """
    item_id = 2353
    _insert_dash(test_db, item_id=item_id, status="release")
    _intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-not-admitted", corrected=True
    )
    test_db.execute(
        "UPDATE qa_requirements SET plan_case_key='release-smoke' WHERE id=%s",
        (broken_id,),
    )
    test_db.commit()

    receipt = _supersede(test_db, broken_id=broken_id, corrected_id=corrected_id)

    assert "admitted_from_requirement_id" not in receipt
    assert "next_admission_notice" not in receipt


def test_an_intake_row_that_no_longer_exists_is_not_invented(test_db) -> None:
    """The key outlives the row it names, and a dangling id names nothing."""
    item_id = 2354
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-dangling-source", corrected=True
    )
    test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (intake_id,))
    test_db.commit()

    receipt = _supersede(test_db, broken_id=broken_id, corrected_id=corrected_id)

    assert "admitted_from_requirement_id" not in receipt
    assert "next_admission_notice" not in receipt


def test_an_intake_row_already_settled_is_named_by_neither(test_db) -> None:
    """No future release admits a settled row, so nothing is left to correct.

    Naming one anyway would send the operator to amend a row the admission
    selector has already stopped reading.
    """
    item_id = 2355
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-settled-source", corrected=True
    )
    replacement_intake = intake_requirement(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s,"
        "superseded_at='2026-09-14T00:03:00Z' WHERE id=%s",
        (replacement_intake, intake_id),
    )
    test_db.commit()

    receipt = _supersede(test_db, broken_id=broken_id, corrected_id=corrected_id)

    assert "admitted_from_requirement_id" not in receipt
    assert "next_admission_notice" not in receipt
