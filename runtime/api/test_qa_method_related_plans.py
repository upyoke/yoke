"""Method detail related-plan outcome fidelity tests."""

from __future__ import annotations

from unittest import mock

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_method_related_plans
from yoke_core.domain.qa_catalog_reads import get_method
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


from runtime.api.qa_method_related_plans_test_support import (
    _case,
    _requirement,
    _run,
)


def test_method_details_roll_up_only_their_current_case_proofs() -> None:
    with test_database() as conn:
        insert_item(conn, id=71, title="Release the product")
        insert_item(conn, id=72, title="Unrelated method snapshot")
        plan = create_plan(
            conn,
            project="yoke",
            slug="release-readiness",
            name="Release readiness",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                _case("backend-suite", 1, "command"),
                _case("changed-path-lint", 2, "command"),
                _case("checkout-flow", 3, "browser-check"),
                _case(
                    "marketing-pages-visual",
                    4,
                    "browser-inspection",
                ),
                _case("signup-smoke", 5, "browser-check"),
                _case("install-cold-start", 6, "machine-state-check"),
            ],
        )
        requirement_specs = [
            ("backend-suite", "command", "2026-07-27T08:00:00Z"),
            ("changed-path-lint", "command", "2026-07-27T08:01:00Z"),
            ("checkout-flow", "browser-check", "2026-07-27T08:02:00Z"),
            (
                "marketing-pages-visual",
                "browser-inspection",
                "2026-07-27T08:03:00Z",
            ),
            ("signup-smoke", "browser-check", "2026-07-27T08:04:00Z"),
            (
                "install-cold-start",
                "machine-state-check",
                "2026-07-27T08:05:00Z",
            ),
        ]
        requirements = {
            case_key: _requirement(
                conn,
                item_id=71,
                plan_id=plan["id"],
                case_key=case_key,
                method_id=method_id,
                created_at=created_at,
            )
            for case_key, method_id, created_at in requirement_specs
        }
        for case_key in ("backend-suite", "changed-path-lint", "checkout-flow"):
            _run(
                conn,
                int(requirements[case_key]["id"]),
                created_at="2026-07-27T09:00:00Z",
                verdict="pass",
                case_outcome="passed",
            )
        inspection_id = int(requirements["marketing-pages-visual"]["id"])
        _run(
            conn,
            inspection_id,
            created_at="2026-07-27T09:01:00Z",
            verdict="pass",
            case_outcome="passed",
        )
        _run(
            conn,
            inspection_id,
            created_at="2026-07-27T09:02:00Z",
            verdict="inconclusive",
            case_outcome="needs_review",
        )
        _run(
            conn,
            int(requirements["install-cold-start"]["id"]),
            created_at="2026-07-27T09:03:00Z",
            verdict=None,
            case_outcome="waiting",
        )
        unrelated = _requirement(
            conn,
            item_id=72,
            plan_id=plan["id"],
            case_key="checkout-flow",
            method_id="command",
            created_at="2026-07-27T10:00:00Z",
        )
        _run(
            conn,
            int(unrelated["id"]),
            created_at="2026-07-27T10:01:00Z",
            verdict="fail",
            case_outcome="failed",
        )

        command = get_method(conn, method_id="command", project="yoke")
        with mock.patch.object(
            qa_method_related_plans,
            "query_rows",
            wraps=qa_method_related_plans.query_rows,
        ) as related_reads:
            browser = get_method(
                conn,
                method_id="browser-check",
                project="yoke",
            )
        assert related_reads.call_count == 2
        inspection = get_method(
            conn,
            method_id="browser-inspection",
            project="yoke",
        )
        machine = get_method(
            conn,
            method_id="machine-state-check",
            project="yoke",
        )

    command_plan = command["plans"][0]
    assert command_plan["case_keys"] == [
        "backend-suite",
        "changed-path-lint",
    ]
    assert command_plan["plan_method_count"] == 4
    assert command_plan["method_is_complete_plan"] is False
    assert command_plan["outcome_summary"]["state"] == "passed"
    assert command_plan["outcome_summary"]["counts"] == {"passed": 2}

    browser_plan = browser["plans"][0]
    assert browser_plan["case_keys"] == ["checkout-flow", "signup-smoke"]
    assert browser_plan["outcome_summary"]["state"] == "running"
    assert browser_plan["outcome_summary"]["counts"] == {
        "passed": 1,
        "queued": 1,
    }

    inspection_plan = inspection["plans"][0]
    assert inspection_plan["case_keys"] == ["marketing-pages-visual"]
    assert inspection_plan["outcome_summary"]["state"] == "needs_review"
    assert inspection_plan["outcome_summary"]["counts"] == {
        "needs_review": 1,
    }

    machine_plan = machine["plans"][0]
    assert machine_plan["case_keys"] == ["install-cold-start"]
    assert machine_plan["outcome_summary"]["state"] == "waiting"
    assert machine_plan["outcome_summary"]["counts"] == {"waiting": 1}


def test_method_rollup_expands_baselines_without_repeating_case_keys() -> None:
    with test_database() as conn:
        insert_item(conn, id=73, title="Prove host baselines")
        plan = create_plan(
            conn,
            project="yoke",
            slug="host-baseline-proof",
            name="Host baseline proof",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                _case(
                    "path-on-shell",
                    1,
                    "machine-state-check",
                    host_baselines=["fresh-host", "shell-preconfigured"],
                )
            ],
        )
        fresh = _requirement(
            conn,
            item_id=73,
            plan_id=plan["id"],
            case_key="path-on-shell",
            method_id="machine-state-check",
            host_baseline="fresh-host",
            created_at="2026-07-27T11:00:00Z",
            waived_at="2026-07-27T11:05:00Z",
        )
        shell = _requirement(
            conn,
            item_id=73,
            plan_id=plan["id"],
            case_key="path-on-shell",
            method_id="machine-state-check",
            host_baseline="shell-preconfigured",
            created_at="2026-07-27T11:01:00Z",
        )
        _run(
            conn,
            int(fresh["id"]),
            created_at="2026-07-27T11:02:00Z",
            verdict="fail",
            case_outcome="failed",
        )
        _run(
            conn,
            int(shell["id"]),
            created_at="2026-07-27T11:03:00Z",
            verdict="pass",
            case_outcome="passed",
        )

        method = get_method(
            conn,
            method_id="machine-state-check",
            project="yoke",
        )

    related = method["plans"][0]
    assert related["case_keys"] == ["path-on-shell"]
    assert related["case_summaries"] == [
        {
            "case_key": "path-on-shell",
            "host_baselines": ["fresh-host", "shell-preconfigured"],
        }
    ]
    assert related["outcome_summary"] == {
        "state": "passed",
        "counts": {"waived": 1, "passed": 1},
        "last_at": "2026-07-27T11:03:00Z",
    }


def test_command_related_plans_follow_product_display_order() -> None:
    with test_database() as conn:
        insert_item(conn, id=74, title="Order command plans")
        plan_specs = [
            (
                "release-readiness",
                [
                    _case("release-backend", 1, "command"),
                    _case("release-lint", 2, "command"),
                    _case("release-browser", 3, "browser-check"),
                ],
            ),
            ("e2e-suite", [_case("e2e", 1, "command")]),
            (
                "full-verification",
                [
                    _case("full-backend", 1, "command"),
                    _case("full-lint", 2, "command"),
                    _case("full-ui", 3, "command"),
                ],
            ),
        ]
        created_plans = {}
        for slug, cases in plan_specs:
            plan = create_plan(
                conn,
                project="yoke",
                slug=slug,
                name=slug,
            )
            replace_plan_cases(
                conn,
                plan_id=plan["id"],
                cases=cases,
            )
            created_plans[slug] = plan
        result_times = {
            "release-readiness": "2026-07-27T13:00:00Z",
            "full-verification": "2026-07-27T12:00:00Z",
            "e2e-suite": "2026-07-26T10:00:00Z",
        }
        for slug, cases in plan_specs:
            for case in cases:
                if case["method_id"] != "command":
                    continue
                requirement = _requirement(
                    conn,
                    item_id=74,
                    plan_id=created_plans[slug]["id"],
                    case_key=case["case_key"],
                    method_id="command",
                    created_at="2026-07-26T09:00:00Z",
                )
                _run(
                    conn,
                    int(requirement["id"]),
                    created_at=result_times[slug],
                    verdict="pass",
                    case_outcome="passed",
                )

        method = get_method(conn, method_id="command", project="yoke")

    assert [plan["slug"] for plan in method["plans"]] == [
        "full-verification",
        "e2e-suite",
        "release-readiness",
    ]
    assert [plan["method_is_complete_plan"] for plan in method["plans"]] == [
        True,
        True,
        False,
    ]
    assert [plan["outcome_summary"]["counts"] for plan in method["plans"]] == [
        {"passed": 3},
        {"passed": 1},
        {"passed": 2},
    ]
