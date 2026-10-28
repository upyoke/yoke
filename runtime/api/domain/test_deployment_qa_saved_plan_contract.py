"""A later standing-plan publication cannot rewrite an older run's plan group.

The first plan group of a plan in a run pins the plan as the release saw it;
a definition published afterwards runs on the next release.
"""

import json

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.domain.test_deployment_qa_plan_groups import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain.deploy_target_occupancy import open_qa_lines
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import PINNED_PLANS, run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases

RUN = "run-saved-contract"
SUCCESSOR = "run-successor"
MEMBERS = (9921, 9922)
STAGE = "item-qa"
SLUG = "release-smoke"


def _group_row(conn, requirement_id):
    return dict(
        conn.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()
    )


@pytest.fixture
def published(test_db, source_checkout, monkeypatch):
    root, git = source_checkout
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(
        source_binding,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(root)),
    )
    pid = _plan(test_db)
    test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, pid))
    stages = _stages(pid)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS, release_lineage=old)
    for member in MEMBERS:
        _attach(test_db, member, pid)
    ids = sorted(ensure_groups(test_db, RUN, STAGE))
    test_db.commit()
    row = _group_row(test_db, ids[0])
    (root / "cases.json").write_text('["new definitions"]\n')
    assert git(root, "commit", "-am", "Publish new definitions").returncode == 0
    new = git(root, "rev-parse", "HEAD").stdout.strip()
    assert git(root, "push", "origin", "stable").returncode == 0
    replace_plan_cases(
        test_db,
        plan_id=pid,
        source_revision=new,
        cases=[
            {
                "case_key": key,
                "method_id": "command",
                "instructions": "new instruction",
                "expected_outcome": "new outcome",
                "method_config": {"command": "false"},
            }
            for key in ("command-smoke", "added-check")
        ],
    )
    test_db.commit()
    return pid, ids, old, new, row


def test_old_contract_survives_publication_without_writes(test_db, published):
    pid, ids, old, new, before = published
    assert ensure_groups(test_db, RUN, STAGE) == []
    for member in MEMBERS:
        result = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
        assert result["created_requirement_ids"] == []
    assert open_qa_lines(test_db, RUN)
    assert _group_row(test_db, ids[0]) == before

    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=None,
        plan=SLUG,
        actor_id="2",
        session_id="saved-contract",
    )
    assert [r["requirement_id"] for r in execution["roster"]] == ids
    _complete_case(test_db, execution)
    (group,) = run_groups(test_db, RUN, STAGE)
    if not group.closed:
        settle_group(test_db, group_subject(test_db, RUN, STAGE, group, require_active=False))
        (group,) = run_groups(test_db, RUN, STAGE)
    assert group.covered_item_ids == MEMBERS


def test_a_later_run_pins_the_published_definition(test_db, published):
    pid, ids, old, new, before = published
    stages = _stages(pid)
    stages[1].pop("cases")
    _seed_run(
        test_db,
        run_id=SUCCESSOR,
        stages=stages,
        members=(),
        existing_members=MEMBERS,
        release_lineage=new,
    )

    created = ensure_groups(test_db, SUCCESSOR, STAGE)
    test_db.commit()

    keys = [
        row["plan_case_key"]
        for row in test_db.execute(
            "SELECT plan_case_key FROM qa_requirements WHERE id=ANY(%s) "
            "ORDER BY case_position",
            (created,),
        ).fetchall()
    ]
    assert keys == ["command-smoke", "added-check"]
    raw = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (SUCCESSOR,)
    ).fetchone()[0]
    pinned = json.loads(str(raw))[PINNED_PLANS][str(pid)]["plan"]
    assert pinned["source_revision"] == new
    with pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch"):
        source_binding.require_candidate_plan(test_db, pinned, RUN)
    assert _group_row(test_db, ids[0]) == before


def _release_members(conn):
    from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

    conn.execute("UPDATE items SET status='release' WHERE id=ANY(%s)", (list(MEMBERS),))
    conn.commit()
    release_seeded_driver(conn, RUN)


def test_takeover_reads_the_pinned_group_without_writes(test_db, published):
    from yoke_core.domain.deployment_run_target_takeover import (
        _moving_members,
        _waiting_run,
    )

    pid, ids, old, new, before = published
    _release_members(test_db)
    new_run = dict(
        test_db.execute("SELECT * FROM deployment_runs WHERE id=%s", (RUN,)).fetchone()
    )
    new_run["id"] = SUCCESSOR
    waiting = _waiting_run(test_db, new_run)
    assert waiting["id"] == RUN
    assert [m["item_id"] for m in _moving_members(test_db, waiting)] == list(MEMBERS)
    assert _group_row(test_db, ids[0]) == before


def test_removing_a_member_owed_an_open_group_keeps_the_pinned_group(
    test_db, published
):
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item

    pid, ids, old, new, before = published
    _release_members(test_db)
    message = cmd_remove_item(
        RUN, MEMBERS[1], reason="member rides successor", session_id="s", actor_id=1
    )
    assert message.startswith("Removed YOK-"), message
    assert _group_row(test_db, ids[0]) == before
    (group,) = run_groups(test_db, RUN, STAGE)
    assert group.open
