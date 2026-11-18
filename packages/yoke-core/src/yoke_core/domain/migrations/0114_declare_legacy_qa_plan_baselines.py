"""Converge saved QA chains on declared baselines and restore remediation retirements."""

import json
from itertools import groupby

from yoke_contracts.qa_case_starting_state import (
    StartingStateError,
    chain_baselines,
    declares_starting_state,
    requires_host_yoke,
)
from yoke_core.domain.db_backend import connection_is_postgres

# Exact retirement reasons of the two batches this migration reverses.
_RETIREMENT_REASONS = (
    "YOK-5450: retained as historical evidence after its attached items finished "
    "and implicit Test Machine starts were retired.",
    "YOK-5450: retain the settled diagnostic plan and its QA evidence as history "
    "after eliminating implicit Test Machine starts.",
)

_CASE_FIELDS = (
    "plan_id", "id", "position", "case_key", "runner_id",
    "required_capability_kinds", "method_config", "entry_surface",
    "host_baselines", "starting_state", "starting_state_reason",
)


def _plans(conn):
    rows = conn.execute(
        "SELECT c.plan_id,c.id,c.position,c.case_key,m.runner_id,m.required_capability_kinds,"
        "c.method_config,c.entry_surface,c.host_baselines,c.starting_state,c.starting_state_reason "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        "ORDER BY c.plan_id,c.position"
    ).fetchall()
    for plan_id, group in groupby(rows, key=lambda row: row[0]):
        cases = [dict(zip(_CASE_FIELDS, row)) for row in group]
        for case in cases:
            case["method_config"] = json.loads(case["method_config"] or "{}")
            case["host_baselines"] = json.loads(case["host_baselines"] or "[]")
        yield plan_id, cases


def _converted(cases):
    """Derive each chain head's baseline after inspecting its inherit followers."""
    changes = []
    follower_requires_yoke = False
    for case in reversed(cases):
        config = case["method_config"]
        variant = (config.get("baseline_configs") or {}).get("fresh-host", config)
        needs_yoke = requires_host_yoke({**case, "method_config": variant})
        needs_yoke = needs_yoke or follower_requires_yoke
        state = case["starting_state"]
        if state == "inherit":
            follower_requires_yoke = needs_yoke
            continue
        follower_requires_yoke = False
        baselines = case["host_baselines"]
        if not declares_starting_state(case):
            if state == "as_is":
                changes.append((case, [], None))
            continue
        if state == "as_is" or (state in (None, "", "baseline") and not baselines):
            changes.append((case, ["shell-preconfigured" if needs_yoke else "fresh-host"], "baseline"))
        elif needs_yoke and "fresh-host" in baselines:
            names = list(dict.fromkeys(
                "shell-preconfigured" if name == "fresh-host" else name
                for name in baselines
            ))
            changes.append((case, names, "baseline"))
    return changes


def _validate(plan_id, cases):
    try:
        chain_baselines(cases)
    except StartingStateError as exc:
        raise ValueError(f"QA plan {plan_id} still cannot materialize: {exc}") from exc


def apply(conn):
    """Update authored definitions in place, preserving materialized QA evidence."""
    marker = "%s" if connection_is_postgres(conn) else "?"
    for plan_id, cases in _plans(conn):
        changes = _converted(cases)
        for case, baselines, state in changes:
            case.update(host_baselines=baselines, starting_state=state, starting_state_reason=None)
            conn.execute(
                f"UPDATE qa_plan_cases SET host_baselines={marker},starting_state={marker},"
                f"starting_state_reason=NULL,updated_at=CURRENT_TIMESTAMP WHERE id={marker}",
                (json.dumps(baselines), state, case["id"]),
            )
        _validate(plan_id, cases)
        if changes:
            conn.execute(
                f"UPDATE qa_plans SET updated_at=CURRENT_TIMESTAMP WHERE id={marker}",
                (plan_id,),
            )
    conn.execute(
        "UPDATE qa_plans SET retired_at=NULL,retired_by_actor_id=NULL,"
        "retirement_reason=NULL,updated_at=CURRENT_TIMESTAMP "
        f"WHERE retired_at IS NOT NULL AND retirement_reason IN ({marker},{marker})",
        _RETIREMENT_REASONS,
    )


def invariants(conn):
    count = conn.execute(
        "SELECT count(*) FROM qa_plan_cases WHERE starting_state='as_is'"
    ).fetchone()[0]
    assert count == 0, f"{count} QA plan cases still use the removed as_is state"
    for plan_id, cases in _plans(conn):
        _validate(plan_id, cases)
