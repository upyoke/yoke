"""The ``run_onboard`` activation signal and the facts its card is drawn from.

A run row appears with the checklist's first write, so the module once
activated — and printed its execution-ready sentence — over a run blocked at
its first hosting step. These drive the handler against real checklist runs:
only a checklist with nothing open activates, and the reported facts name the
blocker, the next step, and the outcomes the universe can actually show.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    ROW_IDS,
    STATUS_BLOCKED,
    STATUS_NOT_NEEDED,
    STATUS_VERIFIED,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.overview_activation import (
    handle_overview_activation_get,
)
from yoke_core.domain.project_onboarding_runs import init_run

HOSTING_ROW_ID = "hosting-setup"
SCAFFOLD_ROW_ID = "scaffold-install"
BLOCKER_TEXT = "aws-admin capability row absent"


def _onboard(actor_id=None):
    outcome = handle_overview_activation_get(FunctionCallRequest(
        function="overview.activation.get",
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=TargetRef(kind="global"),
        payload={},
    ))
    assert outcome.primary_success, outcome.error
    modules = {
        module["key"]: module for module in outcome.result_payload["modules"]
    }
    return modules["run_onboard"]


def _seed_run(conn, run_id, *, row_status=None, blocker=None):
    init_run(
        conn=conn,
        run_id=run_id,
        project_id=1,
        branch=BRANCH_LOCAL_CHECKOUT,
        row_status=row_status,
        blocker=blocker,
    )


def _finished_statuses(**overrides):
    statuses = {row_id: STATUS_VERIFIED for row_id in ROW_IDS}
    statuses.update(overrides)
    return statuses


def _seed_environments(conn, *names):
    now = iso8601_now()
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES (5, 1, 'app', %s)",
        (now,),
    )
    for index, name in enumerate(names):
        conn.execute(
            "INSERT INTO environments (id, site, project_id, name, created_at) "
            "VALUES (%s, 5, 1, %s, %s)",
            (50 + index, name, now),
        )
    conn.commit()


def test_a_blocked_run_stays_unactivated_and_names_its_blocker(test_db):
    _seed_run(
        test_db, "run-blocked",
        row_status={HOSTING_ROW_ID: STATUS_BLOCKED},
        blocker={HOSTING_ROW_ID: BLOCKER_TEXT},
    )

    module = _onboard()

    assert module["state"] != "activated"
    onboard = module["onboard"]
    assert onboard["run_status"] == "blocked"
    assert onboard["blocker"] == {
        "step": "17b", "title": "Hosting setup", "detail": BLOCKER_TEXT,
    }
    # The next open row comes from the checklist's own order, never from
    # sorting the step labels as text ("1", "10", "17a", "9a").
    assert onboard["next"] == {"step": "1", "title": "Package install"}
    assert onboard["steps_total"] == len(ROW_IDS)
    assert 0 < onboard["steps_done"] < onboard["steps_total"]


def test_an_open_run_without_a_blocker_reports_only_its_next_step(test_db):
    _seed_run(test_db, "run-open", row_status=_finished_statuses(**{
        row_id: "needed" for row_id in (HOSTING_ROW_ID, "domain-setup")
    }))

    onboard = _onboard()["onboard"]

    assert onboard["run_status"] == "open"
    assert onboard["blocker"] is None
    assert onboard["next"] == {"step": "17b", "title": "Hosting setup"}
    assert onboard["steps_done"] == len(ROW_IDS) - 2


def test_a_closed_checklist_activates_and_reports_what_it_produced(test_db):
    _seed_environments(test_db, "prod", "stage")
    _seed_run(test_db, "run-done", row_status=_finished_statuses())

    module = _onboard()

    assert module["state"] == "activated"
    onboard = module["onboard"]
    assert onboard["run_status"] == "complete"
    assert onboard["steps_done"] == onboard["steps_total"] == len(ROW_IDS)
    assert onboard["next"] is None and onboard["blocker"] is None
    assert onboard["scaffold_installed"] is True
    assert onboard["strategy_docs"] is False
    # Every registered environment name, the fixture's own included.
    assert onboard["environments"] == ["development", "prod", "stage"]


def test_a_mapped_existing_app_finishes_claiming_no_scaffold(test_db):
    _seed_run(test_db, "run-mapped", row_status=_finished_statuses(**{
        SCAFFOLD_ROW_ID: STATUS_NOT_NEEDED,
    }))

    module = _onboard()

    assert module["state"] == "activated"
    assert module["onboard"]["scaffold_installed"] is False


def test_a_run_that_registered_no_environment_claims_none(test_db):
    test_db.execute("DELETE FROM environments")
    test_db.commit()
    _seed_run(test_db, "run-no-envs", row_status=_finished_statuses())

    module = _onboard()

    assert module["state"] == "activated"
    assert module["onboard"]["environments"] == []


def test_the_latest_run_drives_the_card_after_the_module_activated(test_db):
    _seed_run(test_db, "run-1-done", row_status=_finished_statuses())
    assert _onboard()["state"] == "activated"

    _seed_run(
        test_db, "run-2-blocked",
        row_status={HOSTING_ROW_ID: STATUS_BLOCKED},
        blocker={HOSTING_ROW_ID: BLOCKER_TEXT},
    )
    module = _onboard()

    # The latch is monotone, but the facts under it are live.
    assert module["state"] == "activated"
    assert module["onboard"]["run_status"] == "blocked"
    assert module["onboard"]["blocker"]["detail"] == BLOCKER_TEXT


def test_a_universe_with_no_onboarding_run_reports_no_facts(test_db):
    module = _onboard()

    assert module["state"] != "activated"
    assert module["onboard"] is None
