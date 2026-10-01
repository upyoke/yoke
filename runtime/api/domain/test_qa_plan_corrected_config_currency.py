"""Correction metadata does not make matching executable plan content stale."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_case_currency import (
    CURRENT,
    STALE,
    PlanCaseCurrencyError,
    annotate_plan_currency,
    plan_case_divergence,
    require_current_requirement,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_pass_currency import (
    attach_execution_target_digest,
    has_current_passing_run,
    method_config_was_corrected,
)

TRANSITION = "implemented"
CORRECTED_CONFIG = {"command": "printf corrected"}


def _case(config: dict, *, instructions: str = "Run the command.") -> dict:
    return {
        "case_key": "command",
        "position": 1,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "The command passes.",
        "method_config": config,
    }


def _correct_requirement(conn) -> tuple[int, int]:
    item = insert_item(conn, title="Check corrected plan currency", workflow_id="issue")
    item_id = int(item["id"])
    plan = create_plan(
        conn, project="yoke", slug="corrected-config-currency", name="Currency"
    )
    plan_id = int(plan["id"])
    replace_plan_cases(conn, plan_id=plan_id, cases=[_case({"command": "true"})])
    set_project_default(
        conn, plan_id=plan_id, workflow_id="issue", transition_id=TRANSITION
    )
    result = materialize_for_item(conn, item_id=item_id, transition_id=TRANSITION)
    requirement_id = int(result["created_requirement_ids"][0])
    replace_plan_cases(conn, plan_id=plan_id, cases=[_case(CORRECTED_CONFIG)])
    assert plan_case_divergence(conn, requirement_id).fields == ("method_config",)
    return plan_id, requirement_id


@pytest.mark.parametrize("verdict", [None, "error", "undetermined"])
def test_matching_correction_is_current_without_a_delivery(verdict) -> None:
    with test_database() as conn:
        plan_id, requirement_id = _correct_requirement(conn)
        if verdict is not None:
            insert_qa_run(
                conn,
                qa_requirement_id=requirement_id,
                verdict=verdict,
                verdict_reason="The case did not reach a judgement.",
            )
            conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM deployment_runs").fetchone()[0] == 0

        result = apply_requirement_update(
            conn, requirement_id, "method_config", CORRECTED_CONFIG
        )

        assert result.ok, result.message
        config = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()[0]
        assert method_config_was_corrected(config)
        assert plan_case_divergence(conn, requirement_id) is None
        row = annotate_plan_currency(
            conn, [{"id": requirement_id, "plan_id": plan_id}]
        )[0]
        assert row["plan_currency"] == CURRENT
        assert row["plan_diverging_fields"] == []
        require_current_requirement(conn, requirement_id)


@pytest.mark.parametrize(
    ("config", "instructions", "field"),
    [
        ({"command": "printf changed"}, "Run the command.", "method_config"),
        (CORRECTED_CONFIG, "Run a different assertion.", "instructions"),
    ],
)
def test_corrected_marker_does_not_hide_later_plan_changes(
    config, instructions, field
) -> None:
    with test_database() as conn:
        plan_id, requirement_id = _correct_requirement(conn)
        assert apply_requirement_update(
            conn, requirement_id, "method_config", CORRECTED_CONFIG
        ).ok
        replace_plan_cases(
            conn, plan_id=plan_id, cases=[_case(config, instructions=instructions)]
        )

        divergence = plan_case_divergence(conn, requirement_id)

        assert divergence.state == STALE
        assert divergence.fields == (field,)
        with pytest.raises(PlanCaseCurrencyError, match="plan_case_superseded"):
            require_current_requirement(conn, requirement_id)


def test_matching_plan_correction_still_invalidates_unstamped_historical_green() -> (
    None
):
    with test_database() as conn:
        _, requirement_id = _correct_requirement(conn)
        digest = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            verdict="pass",
            raw_result=attach_execution_target_digest(None, digest),
        )
        conn.commit()
        assert has_current_passing_run(conn, requirement_id)

        assert apply_requirement_update(
            conn, requirement_id, "method_config", CORRECTED_CONFIG
        ).ok

        assert plan_case_divergence(conn, requirement_id) is None
        assert not has_current_passing_run(conn, requirement_id)
