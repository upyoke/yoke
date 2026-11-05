"""An item removed from its run retires a broken source without a waiver.

Removing a member whose admitted post_deploy copy failed leaves that copy
behind on a run that no longer grades the item, and no corrected case can
be materialized there any more. Requiring a passing run replacement of the
copy before retiring the source made the correction impossible and left an
operator waiver as the only exit. The supported route: remove the item from
the run, retire the source in favor of the corrected item requirement, and
let the next release prove the corrected body.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)
from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.qa_source_retirement_test_support import (
    CORRECTED_INSTRUCTIONS,
    _corrected_item_requirement,
    _retire,
)
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    admitted_copy,
    deliver_with_failing_admitted_copy,
    execute_member_stage,
    succeed_run,
)
from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    source_obligation_consumed,
    unsatisfied_blocking,
)
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.qa_requirement_supersession import QaSupersessionError


def test_removed_member_retires_its_source_and_next_release_closes(test_db):
    item_id = 2380
    first_run = "run-removed-member"
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, copy_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=first_run, corrected=False
    )
    remove_member_on(test_db, first_run, item_id, reason="rides the next release")
    test_db.commit()
    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)

    receipt = _retire(test_db, source_id=source_id, corrected_id=corrected_id)

    assert receipt["superseded_by_requirement_id"] == corrected_id
    assert "run_replacement_requirement_id" not in receipt
    assert (
        f"Requirement {corrected_id} carries the obligation"
        in (receipt["proof_owed_notice"])
    )
    # The corrected requirement still owes its own proof.
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=corrected_id
    )

    next_run = "run-removed-member-next"
    _seed_selected_requirement_run(
        test_db, run_id=next_run, item_id=item_id, requirement_id=corrected_id
    )
    admissible = admissible_post_deploy_requirement_ids(
        test_db, run_id=next_run, item_id=item_id
    )
    assert corrected_id in admissible
    assert source_id not in admissible
    next_copy = admitted_copy(test_db, run_id=next_run, item_id=item_id)
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (next_copy,)
        ).fetchone()["instructions"]
        == CORRECTED_INSTRUCTIONS
    )
    execute_member_stage(
        test_db, run_id=next_run, item_id=item_id, verdicts={next_copy: "pass"}
    )
    succeed_run(test_db, next_run)

    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=corrected_id
    )
    blocking = unsatisfied_blocking(test_db, item_id=item_id, target_status="done")
    assert blocking.count == 0, blocking.rows
    # Nothing on the item was waived to get here.
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE (item_id=%s OR "
            "deployment_member_item_id=%s) AND waived_at IS NOT NULL",
            (item_id, item_id),
        ).fetchone()[0]
        == 0
    )
    assert copy_id != next_copy


def test_member_still_on_the_run_must_correct_the_copy_first(test_db):
    item_id = 2381
    run_id = "run-member-still-on"
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, copy_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=False
    )
    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)

    with pytest.raises(QaSupersessionError) as refusal:
        _retire(test_db, source_id=source_id, corrected_id=corrected_id)

    message = str(refusal.value)
    assert message.startswith("source_retirement_unproven:")
    assert f"#{copy_id}" in message
    assert run_id in message
    assert "--replaces" in message
    assert "yoke deployment-runs remove-item" in message


def test_failed_run_no_longer_holds_the_source(test_db):
    item_id = 2382
    run_id = "run-failed-holder"
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, _copy_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=False
    )
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (run_id,))
    test_db.commit()
    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)

    receipt = _retire(test_db, source_id=source_id, corrected_id=corrected_id)

    assert "proof_owed_notice" in receipt
