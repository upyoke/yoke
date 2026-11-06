"""Correcting member-owned attached plans preserves their scope and evidence."""

from runtime.api.domain.deployment_qa_singleton_correction_test_support import (
    _correct as _correct,
)


import json

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    _attach,
    _seed,
)
from runtime.api.domain.deployment_qa_shared_plans_test_support import _fail
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_plan_ownership import _snapshot
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_item_deployment_request import resolve_item_deployment_request
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements

STAGE = "item-qa"


def _subject(member=MEMBERS[0]):
    return dict(
        deployment_run_id=RUN, deployment_stage=STAGE, deployment_member_item_id=member
    )


def _single(conn):
    plan = _seed(conn, attached=MEMBERS[:1])
    set_current_stage(conn, RUN, STAGE)
    conn.commit()
    materialized = materialize_deployment_qa_stage(conn, **_subject())
    return plan, materialized["created_requirement_ids"][0]


def _request(conn, plan):
    return FunctionCallRequest(
        function="qa.plan.rematerialize",
        actor=ActorContext(actor_id="2", session_id="owner"),
        target=TargetRef(kind="item", item_id=MEMBERS[0], project_id="1"),
        payload={"deployment_stage": STAGE, "plan": str(plan)},
    )


@pytest.mark.parametrize("kind", ["single", "shared", "correction"])
def test_explicit_item_plan_keeps_member_unless_the_plan_is_shared(
    test_db, monkeypatch, kind
):
    from yoke_core.domain import qa_item_deployment_request as routing

    plan = _seed(test_db, attached=MEMBERS if kind == "shared" else MEMBERS[:1])
    set_current_stage(test_db, RUN, STAGE)
    test_db.commit()
    if kind == "correction":
        plan = _plan(test_db, "member-correction")
    monkeypatch.setattr(
        routing, "latest_qa_member_run", lambda *args, **kwargs: {"id": RUN}
    )
    request = resolve_item_deployment_request(test_db, _request(test_db, plan))
    assert request.target.deployment_run_id == RUN
    if kind == "shared":
        assert "deployment_member" not in request.payload
    else:
        assert request.payload["deployment_member"] == render_item_ref(
            test_db, MEMBERS[0]
        )


def test_failed_singleton_rematerializes_its_pinned_contract_and_credits_member(
    test_db,
):
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    plan, failed = _single(test_db)
    before = _snapshot(test_db, RUN)
    _fail(test_db, failed)
    _correct(test_db, plan)
    result = rematerialize_for_deployment_stage(test_db, **_subject(), plan=str(plan))
    corrected = result["created_requirement_ids"]
    assert len(corrected) == 1 and corrected != [failed]
    after = _snapshot(test_db, RUN)
    assert after["item_qa_plan_owners"] == before["item_qa_plan_owners"]
    assert (
        after["plan_groups"][str(plan)]["cases"][0]["instructions"]
        == "Run the corrected member probe."
    )
    old = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (failed,)
    ).fetchone()
    assert old[0] == before["plan_groups"][str(plan)]["cases"][0]["instructions"]
    execution = begin_plan_execution(
        test_db, **_subject(), plan=str(plan), actor_id="2", session_id="owner"
    )
    assert [row["requirement_id"] for row in execution["roster"]] == corrected
    _complete_case(test_db, execution)
    assert current_item_qa(
        test_db, run_id=RUN, item_id=MEMBERS[0], current_stage=STAGE
    ).accepted


def test_new_correction_plan_replaces_only_the_selected_member_failure(test_db):
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    plan, failed = _single(test_db)
    _fail(test_db, failed)
    correction = _plan(test_db, "correction-only")
    _correct(test_db, correction)
    replacements, scopes = resolve_correction_selection(
        test_db, [{"requirement_id": failed}]
    )
    result = materialize_deployment_qa_stage(
        test_db,
        **_subject(),
        agent_plan=str(correction),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed}),
        commit=False,
    )
    corrected = result["created_requirement_ids"]
    assert corrected
    declare_replacements(test_db, replacements, materialized_requirement_ids=corrected)
    test_db.commit()
    execution = begin_plan_execution(
        test_db,
        **_subject(),
        plan=str(correction),
        actor_id="2",
        session_id="correction",
    )
    assert {row["requirement_id"] for row in execution["roster"]} == set(corrected)
    assert execution["deployment_member_item_id"] == MEMBERS[0]
    finish_plan_execution(
        test_db, execution, state="aborted", reason="Probe needs correction"
    )
    _fail(test_db, corrected[0])
    _correct(test_db, correction, label="corrected again")
    retried = rematerialize_for_deployment_stage(
        test_db, **_subject(), plan=str(correction)
    )["created_requirement_ids"]
    assert len(retried) == 1 and retried != corrected
    execution = begin_plan_execution(
        test_db, **_subject(), plan=str(correction), actor_id="2", session_id="retry"
    )
    assert execution["roster"][0]["requirement_id"] == retried[0]
    assert (
        execution["roster"][0]["instructions"]
        == "Run the corrected again member probe."
    )
    _complete_case(test_db, execution)
    assert current_item_qa(
        test_db, run_id=RUN, item_id=MEMBERS[0], current_stage=STAGE
    ).accepted
    assert _snapshot(test_db, RUN)["item_qa_plan_owners"][str(plan)] == MEMBERS[0]
    from yoke_core.domain.deployment_qa_snapshot_correction import (
        refresh_selected_cases,
    )
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    accepted = _snapshot(test_db, RUN)
    _correct(test_db, correction, label="changed after acceptance")
    refresh_selected_cases(
        test_db,
        run_id=RUN,
        stage=STAGE,
        member=MEMBERS[0],
        plan_id=correction,
        cases=_plan_snapshot(test_db, correction, project_id=1)["cases"],
    )
    assert _snapshot(test_db, RUN) == accepted
    selections = _snapshot(test_db, RUN).get("selections", [])
    assert len([value for value in selections if value.get("member_item_id")]) == 1
    from yoke_core.domain.deployment_qa_stage_materialization import (
        QaCasesNotSelectedError,
    )

    with pytest.raises(QaCasesNotSelectedError):
        materialize_deployment_qa_stage(test_db, **_subject(MEMBERS[1]))
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s AND plan_id=%s",
            (RUN, MEMBERS[1], correction),
        ).fetchone()[0]
        == 0
    )


def test_singleton_refresh_preserves_another_members_passed_contract(test_db):
    plan, failed = _single(test_db)
    _attach(test_db, MEMBERS[1], plan)
    materialize_deployment_qa_stage(test_db, **_subject(MEMBERS[1]))
    execution = begin_plan_execution(
        test_db, **_subject(MEMBERS[1]), actor_id="2", session_id="late-owner"
    )
    _complete_case(test_db, execution)
    _fail(test_db, failed)
    before = _snapshot(test_db, RUN)
    _correct(test_db, plan)
    result = rematerialize_for_deployment_stage(test_db, **_subject())
    assert len(result["created_requirement_ids"]) == 1
    assert _snapshot(test_db, RUN) == before
    row = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s",
        (result["created_requirement_ids"][0],),
    ).fetchone()
    assert row[0] == "Run the corrected member probe."


def test_missing_singleton_contract_still_refuses_historical_reconstruction(test_db):
    plan, _ = _single(test_db)
    payload = _snapshot(test_db, RUN)
    payload["plan_groups"].pop(str(plan))
    test_db.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(payload), RUN),
    )
    test_db.commit()
    with pytest.raises(
        QaPlanError, match="selected plan owner is missing or ambiguous"
    ):
        rematerialize_for_deployment_stage(test_db, **_subject())


def test_member_correction_refresh_keeps_its_admitted_case_and_baseline_scope(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine

    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = {
        "case_key": "command-smoke",
        "method_id": "machine-state-check",
        "instructions": "check the host",
        "expected_outcome": "passes",
        "method_config": {
            "test_machine": "mac-mini-lab",
            "assertions": [{"argv": ["/usr/bin/true"]}],
        },
        "host_baselines": ["fresh-host", "shell-preconfigured"],
    }
    plan = _seed(test_db, attached=MEMBERS[:1])
    replace_plan_cases(test_db, plan_id=plan, cases=[case])
    set_current_stage(test_db, RUN, STAGE)
    test_db.commit()
    initial = materialize_deployment_qa_stage(test_db, **_subject())
    rows = test_db.execute(
        "SELECT id,host_baseline FROM qa_requirements WHERE id=ANY(%s)",
        (initial["created_requirement_ids"],),
    ).fetchall()
    failed = next(row["id"] for row in rows if row["host_baseline"] == "fresh-host")
    _fail(test_db, failed)
    correction = _plan(test_db, "baseline-correction")
    replace_plan_cases(
        test_db, plan_id=correction, cases=[{**case, "instructions": "corrected host"}]
    )
    replacements, scopes = resolve_correction_selection(
        test_db, [{"requirement_id": failed}]
    )
    result = materialize_deployment_qa_stage(
        test_db,
        **_subject(),
        agent_plan=str(correction),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed}),
        commit=False,
    )
    corrected = result["created_requirement_ids"]
    assert len(corrected) == 1
    declare_replacements(test_db, replacements, materialized_requirement_ids=corrected)
    test_db.commit()
    _fail(test_db, corrected[0])
    replace_plan_cases(
        test_db,
        plan_id=correction,
        cases=[
            {**case, "instructions": "corrected host again"},
            {**case, "case_key": "unadmitted-probe", "position": 2},
        ],
    )
    retried = rematerialize_for_deployment_stage(
        test_db, **_subject(), plan=str(correction)
    )
    assert len(retried["created_requirement_ids"]) == 1
    admitted = test_db.execute(
        "SELECT plan_case_key,host_baseline FROM qa_requirements WHERE deployment_run_id=%s AND plan_id=%s",
        (RUN, correction),
    ).fetchall()
    assert len(admitted) == 2
    assert all(row["host_baseline"] == "fresh-host" for row in admitted)
    assert all(row["plan_case_key"].startswith("command-smoke") for row in admitted)
