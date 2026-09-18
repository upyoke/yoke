"""A deployment run's case is judged by its deployed target, not by a lane.

The verification tree binding keeps an item's own gate from being collected
in a tree nobody changed. A deployment-run case has no such tree: it observes
the candidate the run deployed, and whichever item claim the executing
session happens to hold says nothing about it. Binding it anyway refused
every routine invocation and pushed member owners onto the flag reserved for
a deliberate cross-tree run.
"""

from __future__ import annotations

from yoke_core.domain.qa_case_tree_binding_scope import (
    deployment_binding_notice,
    session_lane_binds_case,
)

RUN_ID = "run-20260101-001"


def _deployment_case() -> dict:
    return {
        "requirement_id": 27758,
        "item_id": None,
        "deployment_run_id": RUN_ID,
        "deployment_stage": "item-qa",
        "execution_target": {
            "deployment": {"run_id": RUN_ID, "stage": "item-qa"},
            "endpoints": {"app_url": "https://app.example.test"},
            "observed_url": "https://app.example.test",
        },
    }


def test_an_item_case_is_still_bound_to_the_sessions_claimed_lane() -> None:
    assert session_lane_binds_case({"item_id": 3400, "deployment_run_id": None})


def test_a_deployment_run_case_is_not_bound_to_any_lane() -> None:
    assert not session_lane_binds_case(_deployment_case())


def test_the_notice_names_the_run_stage_and_endpoint_that_do_bind_it() -> None:
    notice = deployment_binding_notice(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
    )

    assert RUN_ID in notice
    assert "item-qa" in notice
    assert "https://app.example.test" in notice
    assert "'/checkout'" in notice
