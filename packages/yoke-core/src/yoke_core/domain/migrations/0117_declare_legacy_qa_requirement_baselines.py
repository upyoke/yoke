"""Converge open QA requirements still starting ``as_is`` on a declared baseline.

YOK-5450 removed the ``as_is`` starting state, and 0114 converted the saved
plan cases. Requirements materialized before then (item cases, planless
cases and their deployment-run copies) still say ``as_is`` with no
``host_baseline``, so begin refuses them and neither update (once a copy
ran) nor supersede (the baseline is part of the scope) can correct them.

This pass rewrites each open ``as_is`` row in place with 0114's derivation,
built on the same contract checks (an entry may not import another entry,
and 0114 is applied history): a machine case that needs Yoke on its host starts from
``shell-preconfigured``, any other machine case from ``fresh-host``, and a
case that runs on no Test Machine declares no starting state. The open
``inherit`` rows right behind a converted head take its baseline, and their
Yoke needs count toward the head's choice. Retracted, superseded and waived
rows, and ``qa_runs``, keep their history unchanged; replay is a no-op.
"""

import json

from yoke_contracts.qa_case_starting_state import (
    declares_starting_state,
    requires_host_yoke,
)
from yoke_core.domain.db_backend import connection_is_postgres

_OPEN = (
    "retracted_at IS NULL AND superseded_by_requirement_id IS NULL "
    "AND waived_at IS NULL"
)

# Columns that place a materialized case in one chain of one plan execution.
_CHAIN_KEY = (
    "item_id", "epic_id", "task_num", "deployment_run_id",
    "standalone_execution_id", "deployment_stage", "deployment_member_item_id",
    "workflow_transition_id", "qa_phase", "execution_target_digest",
    "plan_id", "baseline_position",
)
_FIELDS = (
    "id", *_CHAIN_KEY, "case_position", "plan_case_key", "runner_id",
    "capability_requirements", "method_config", "entry_surface",
    "starting_state",
)


def _needs_yoke(case):
    config = case["method_config"]
    variant = (config.get("baseline_configs") or {}).get("fresh-host", config)
    return requires_host_yoke({**case, "method_config": variant})


def _baseline(chain):
    """The head's declared state and baseline, as 0114 derives a chain head."""
    head = chain[0]
    if not declares_starting_state(head):
        return None, None
    if any(_needs_yoke(case) for case in chain):
        return "baseline", "shell-preconfigured"
    return "baseline", "fresh-host"


def _cases(conn):
    rows = conn.execute(
        f"SELECT {','.join(_FIELDS)} FROM qa_requirements "
        f"WHERE {_OPEN} AND (starting_state='as_is' "
        "OR (starting_state='inherit' AND host_baseline IS NULL)) "
        "ORDER BY id"
    ).fetchall()
    cases = []
    for row in rows:
        case = dict(zip(_FIELDS, row))
        try:
            config = json.loads(case["method_config"] or "{}")
        except ValueError as exc:
            raise ValueError(
                f"QA requirement {case['id']} has unreadable method_config, so "
                f"its baseline cannot be derived: {exc}; repair the row, then "
                "rerun this migration"
            ) from exc
        case.update(
            case_key=case["plan_case_key"] or f"requirement-{case['id']}",
            method_config=config,
            required_capability_kinds=case["capability_requirements"],
            host_baselines=[],
        )
        cases.append(case)
    return cases


def _chains(cases):
    """Each open ``as_is`` head with the contiguous ``inherit`` rows behind it."""
    by_slot = {
        (tuple(case[k] for k in _CHAIN_KEY), case["case_position"]): case
        for case in cases
        if case["starting_state"] == "inherit" and case["plan_id"] is not None
    }
    for head in cases:
        if head["starting_state"] != "as_is":
            continue
        chain = [head]
        key = tuple(head[k] for k in _CHAIN_KEY)
        position = head["case_position"]
        while position is not None and (key, position + 1) in by_slot:
            position += 1
            chain.append(by_slot[(key, position)])
        yield chain


def apply(conn):
    """Declare each open ``as_is`` chain's baseline on its stored rows."""
    marker = "%s" if connection_is_postgres(conn) else "?"
    for chain in _chains(_cases(conn)):
        head = chain[0]
        state, baseline = _baseline(chain)
        conn.execute(
            f"UPDATE qa_requirements SET starting_state={marker},"
            f"host_baseline={marker},starting_state_reason=NULL WHERE id={marker}",
            (state, baseline, head["id"]),
        )
        if baseline is None:
            continue
        for follower in chain[1:]:
            conn.execute(
                f"UPDATE qa_requirements SET host_baseline={marker} "
                f"WHERE id={marker} AND host_baseline IS NULL",
                (baseline, follower["id"]),
            )


def invariants(conn):
    """No open requirement or saved plan case still starts ``as_is``."""
    for table, where in (
        ("qa_requirements", f" AND {_OPEN}"),
        ("qa_plan_cases", ""),
    ):
        count = conn.execute(
            f"SELECT count(*) FROM {table} WHERE starting_state='as_is'{where}"
        ).fetchone()[0]
        assert count == 0, (
            f"{count} open {table} rows still use the removed as_is state; "
            "rerun migration 0117_declare_legacy_qa_requirement_baselines"
        )
