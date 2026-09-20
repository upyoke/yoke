"""What the attach says about a run that can, or cannot, act on its member.

The failure this covers is an attach that told the caller nothing: four items
joined a run whose every stage was run-scoped, and the command accepted all
four in silence. The answer has two halves — can this run check the member,
can it close it — and a flow with no item-scoped stage is the ordinary shape
of most delivery, so the missing stage alone must not refuse anything.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_item_flow_resolution import membership_closes_item
from yoke_core.domain.deployment_member_run_coverage import (
    inert_membership_notice,
    member_coverage_notice,
    member_run_coverage,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.project_identity import render_item_ref


RUN_SCOPED_STAGES = [
    {"name": "merged", "step_runner": "auto", "stage_kind": "execution"},
    {"name": "warm-up", "step_runner": "warm-up", "stage_kind": "execution"},
    {"name": "complete", "step_runner": "auto", "stage_kind": "execution"},
]

ITEM_SCOPED_STAGES = RUN_SCOPED_STAGES + [
    {
        "name": "item-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {
            "kind": "persistent_environment",
            "environment": "prod",
            "source_stage": "warm-up",
        },
        "verdict": {"mode": "agent_only"},
    },
]


def _flow(conn: Any, flow_id: str, stages: list[dict[str, Any]]) -> None:
    """Insert one definition directly.

    The activation validator asks whether a QA target can prove its deployed
    identity, which is a different subject from what a run can do for a
    member, and it refuses the minimal stage list this needs.
    """
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version) VALUES "
        "(%s,1,%s,'',%s,'2026-09-19T00:00:00Z','active',2)",
        (flow_id, flow_id, json.dumps(stages)),
    )


def _run(conn: Any, run_id: str, flow_id: str, *, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id, project_id, flow, release_lineage, status, created_at) "
        "VALUES (%s, %s, %s, 'main', 'created', '2026-09-19T00:00:00Z')",
        (run_id, project_id, flow_id),
    )


def _item(conn: Any, item_id: int, *, flow: str = "") -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id - 9000,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow,
    )


def test_a_run_that_can_neither_check_nor_close_says_so_and_names_the_flow(
    test_db: Any,
) -> None:
    _flow(test_db, "coverage-prod", RUN_SCOPED_STAGES)
    _flow(test_db, "coverage-stage", RUN_SCOPED_STAGES)
    _run(test_db, "run-coverage-stage", "coverage-stage")
    _item(test_db, 9401, flow="coverage-prod")
    test_db.commit()

    coverage = member_run_coverage(
        test_db, run_id="run-coverage-stage", item_id=9401
    )
    assert not coverage.checks
    assert not coverage.closes
    assert coverage.inert

    notice = member_coverage_notice(
        test_db, run_id="run-coverage-stage", item_id=9401
    )
    assert "declares no item-scoped stage" in notice
    assert "no requirement snapshot freezes" in notice
    assert "'coverage-prod'" in notice
    # The consequence membership still has, which is the part the silent
    # attach hid: a held landing is one the real release stops proposing.
    assert "counts as held by a release" in notice
    assert "will not enroll it" in notice


def test_the_inert_notice_only_offers_recoveries_that_exist(
    test_db: Any,
) -> None:
    _flow(test_db, "recovery-prod", RUN_SCOPED_STAGES)
    _flow(test_db, "recovery-stage", RUN_SCOPED_STAGES)
    _run(test_db, "run-recovery-stage", "recovery-stage")
    _item(test_db, 9402, flow="recovery-prod")
    test_db.commit()

    notice = member_coverage_notice(
        test_db, run_id="run-recovery-stage", item_id=9402
    )
    assert "Attach the item to a run of 'recovery-prod' instead" in notice
    assert "yoke deployment-runs validate-composition" in notice
    assert "yoke deployment-runs terminalize run-recovery-stage" in notice
    # There is no registered surface that detaches a member, so the notice
    # must never send the caller looking for one.
    assert "remove" not in notice.lower()
    assert "detach" not in notice.lower()


def test_a_run_scoped_completion_flow_is_not_warned_about(test_db: Any) -> None:
    """The regression a refusal would have caused.

    Most delivery flows declare no item-scoped stage and are still exactly
    the run that closes their members, so this shape has to stay quiet.
    """
    _flow(test_db, "closes-prod", RUN_SCOPED_STAGES)
    _run(test_db, "run-closes-prod", "closes-prod")
    _item(test_db, 9403, flow="closes-prod")
    test_db.commit()

    coverage = member_run_coverage(test_db, run_id="run-closes-prod", item_id=9403)
    assert not coverage.checks
    assert coverage.closes
    assert not coverage.inert

    notice = member_coverage_notice(
        test_db, run_id="run-closes-prod", item_id=9403
    )
    assert "is this item's completion flow, so it can close the item" in notice
    assert "counts as held by a release" not in notice
    assert inert_membership_notice(test_db, "run-closes-prod") == ""


def test_an_item_scoped_stage_is_named_on_the_attach(test_db: Any) -> None:
    _flow(test_db, "checks-prod", ITEM_SCOPED_STAGES)
    _run(test_db, "run-checks-prod", "checks-prod")
    _item(test_db, 9404, flow="checks-prod")
    test_db.commit()

    coverage = member_run_coverage(test_db, run_id="run-checks-prod", item_id=9404)
    assert coverage.item_scoped_stages == ("item-qa",)
    assert coverage.checks and coverage.closes

    notice = member_coverage_notice(
        test_db, run_id="run-checks-prod", item_id=9404
    )
    assert "answer for itself at QA stage 'item-qa'" in notice
    assert "counts as held by a release" not in notice


def test_a_stage_run_that_can_check_but_not_close_is_not_warned_about(
    test_db: Any,
) -> None:
    """Checking is enough on its own: the member's evidence is collected."""
    _flow(test_db, "split-prod", RUN_SCOPED_STAGES)
    _flow(test_db, "split-stage", ITEM_SCOPED_STAGES)
    _run(test_db, "run-split-stage", "split-stage")
    _item(test_db, 9405, flow="split-prod")
    test_db.commit()

    coverage = member_run_coverage(test_db, run_id="run-split-stage", item_id=9405)
    assert coverage.checks
    assert not coverage.closes
    assert not coverage.inert
    notice = member_coverage_notice(
        test_db, run_id="run-split-stage", item_id=9405
    )
    assert "cannot close the item, whose completion flow is 'split-prod'" in notice
    assert "counts as held by a release" not in notice


def test_an_unresolved_completion_flow_is_named_as_its_own_reason(
    test_db: Any,
) -> None:
    _flow(test_db, "unresolved-stage", RUN_SCOPED_STAGES)
    _run(test_db, "run-unresolved", "unresolved-stage")
    _item(test_db, 9406)
    test_db.commit()

    notice = member_coverage_notice(test_db, run_id="run-unresolved", item_id=9406)
    assert "the item resolves no completion flow at all" in notice
    assert "--field deployment_flow" in notice


def test_the_attach_warns_without_refusing(test_db: Any) -> None:
    _flow(test_db, "accepts-prod", RUN_SCOPED_STAGES)
    _flow(test_db, "accepts-stage", RUN_SCOPED_STAGES)
    _run(test_db, "run-accepts-stage", "accepts-stage")
    _item(test_db, 9407, flow="accepts-prod")
    test_db.commit()

    message = cmd_add_item("run-accepts-stage", 9407)

    assert message.startswith("Added ")
    assert "run-accepts-stage" in message
    assert "declares no item-scoped stage" in message
    assert "'accepts-prod'" in message
    members = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s",
        ("run-accepts-stage",),
    ).fetchall()
    assert [int(row[0]) for row in members] == [9407]


def test_the_run_wide_preview_names_only_the_member_receiving_nothing(
    test_db: Any,
) -> None:
    _flow(test_db, "preview-prod", RUN_SCOPED_STAGES)
    _flow(test_db, "preview-stage", RUN_SCOPED_STAGES)
    _run(test_db, "run-preview-stage", "preview-stage")
    _item(test_db, 9408, flow="preview-stage")
    _item(test_db, 9409, flow="preview-prod")
    test_db.commit()
    cmd_add_item("run-preview-stage", 9408)
    cmd_add_item("run-preview-stage", 9409)

    notice = inert_membership_notice(test_db, "run-preview-stage")

    assert render_item_ref(test_db, 9409) in notice
    assert render_item_ref(test_db, 9408) not in notice


def test_a_carrier_run_closes_the_item_whatever_its_flow() -> None:
    """Another project's run that recorded this project's commit can close it."""
    assert membership_closes_item(
        run_flow="platform-production",
        completion_flow="yoke-hosted-production",
        run_project_id=2,
        item_project_id=1,
        source_sha="abc123",
    )
    # Same project, other flow, is not completion authority.
    assert not membership_closes_item(
        run_flow="yoke-hosted-stage",
        completion_flow="yoke-hosted-production",
        run_project_id=1,
        item_project_id=1,
        source_sha="abc123",
    )
    # A carrier that recorded no commit for the item's project shipped
    # nothing for it, so it delivers nothing for it either.
    assert not membership_closes_item(
        run_flow="platform-production",
        completion_flow="yoke-hosted-production",
        run_project_id=2,
        item_project_id=1,
        source_sha="",
    )
