"""Visible plan variants keep the same inherited machine state as execution."""

import pytest

from yoke_core.domain.deployment_member_qa_projection import _same_content
from yoke_core.domain.deployment_member_qa_sources import definitions, identity


def case(key, **fields):
    return {
        "case_key": key,
        "runner_id": "host_control",
        "method_id": "terminal-check",
        "instructions": "Current plan instruction",
        "method_config": {},
        "expected_outcome": "Current plan outcome",
        "host_baselines": [],
        **fields,
    }


def visible(sources, cases):
    return definitions(
        sources,
        [{"plan": {"id": 3, "slug": "installer"}, "cases": cases}],
        environments={},
        environment_names={"prod"},
        dynamic=False,
    )


@pytest.mark.parametrize("encoded", [False, True])
def test_inherited_case_reconciles_old_source_with_current_deployment_copy(encoded):
    baseline = "fresh-host"
    current = case("handoff", starting_state="inherit")
    source = {
        **current,
        "id": 10,
        "plan_id": 3,
        "plan_case_key": "handoff",
        "host_baseline": baseline,
        "instructions": "Old intake instruction",
    }
    copy = {
        **current,
        "id": 20,
        "plan_id": 3,
        "plan_case_key": "handoff",
        "host_baseline": baseline,
        "target_env": "prod",
    }
    rows = visible(
        [source],
        [
            case(
                "install",
                host_baselines='["fresh-host"]' if encoded else [baseline],
            ),
            current,
        ],
    )
    handoff = [row for row in rows.values() if row["case_key"] == "handoff"]
    # The prior reader emitted both a stale baseline row and a new NULL row,
    # rejecting the real copy and inventing a source-only pending obligation.
    assert len(handoff) == 1
    assert handoff[0]["host_baseline"] == baseline
    assert handoff[0]["source_requirement_id"] == source["id"]
    assert identity(copy) in rows
    assert _same_content(copy, rows[identity(copy)])


def test_inheritance_expands_every_predecessor_baseline_before_target_filtering():
    rows = visible(
        [],
        [
            case(
                "install",
                host_baselines=["fresh-host", "browser-approved"],
                target_envs=["stage"],
            ),
            case("handoff", starting_state="inherit"),
            case("inspect", starting_state="inherit"),
            case("existing", starting_state="as_is"),
            case("follow-existing", starting_state="inherit"),
        ],
    )
    assert {(row["case_key"], row["host_baseline"]) for row in rows.values()} == {
        ("handoff", "fresh-host"),
        ("handoff", "browser-approved"),
        ("inspect", "fresh-host"),
        ("inspect", "browser-approved"),
        ("existing", None),
        ("follow-existing", None),
    }
