"""The requirement row one QA plan case materializes into.

Materializing a plan case writes a *copy* of it onto ``qa_requirements``, and
the only link back is ``(plan_id, plan_case_key, host_baseline)``. The copy is
not a field-for-field mirror: ``success_policy_id`` plus
``success_policy_params`` collapse into one ``success_policy`` document, the
plan's ``host_baselines`` array fans out into one row per baseline,
``method_name`` / ``runner_id`` / ``verdict_path`` arrive from ``qa_methods``
rather than from the case, and ``capability_requirements`` is derived through
:func:`materialized_capability_kinds` rather than stored anywhere.

That transform used to live twice, inline in the insert and the refresh, which
is why nothing could answer "is this row still what its plan says?" without
re-deriving it by hand. It lives here once instead, so the writers and
:mod:`qa_plan_case_currency` read the same derivation: what a row SHOULD be is
computed by the same code that decides what it IS written as.

Validation stays with the writers. This function derives, and refuses only a
case its own method could never run -- a read asking what a plan case means
today gets an answer or a named reason, never a silent partial one.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from yoke_core.domain.machine_qa_case_machine import materialized_capability_kinds
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_method_capabilities import encoded_capability_kinds
from yoke_core.domain.qa_plan_management import QaPlanError, _json


def require_runnable_case(case: Any) -> dict:
    """Return the case config, refusing one its method could never run.

    Plan-case authoring validates the same contract, so this is the second
    reader of it — and the one that matters, because materialization is
    what mints the executable requirement. A row written around authoring
    would otherwise become a requirement whose only possible outcome is a
    runner refusing it at gate time.
    """
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    raw_config = case["method_config"] or {}
    config = (
        dict(raw_config)
        if isinstance(raw_config, Mapping)
        else json.loads(str(raw_config))
    )
    try:
        return validate_method_config(str(case["config_contract_id"]), config)
    except QaMethodConfigError as exc:
        raise QaPlanError(f"case {str(case['case_key'])!r}: {exc}") from exc


def _success_policy(plan: Any, case: Any) -> str:
    """One policy document from the case's override and the plan's default."""
    policy_id = case["success_policy_id"] or plan["success_policy_id"]
    raw_params = case["success_policy_params"]
    if raw_params is None:
        raw_params = plan["success_policy_params"]
    params = (
        dict(raw_params)
        if isinstance(raw_params, Mapping)
        else json.loads(str(raw_params))
    )
    return _json({"id": policy_id, "params": params})


def materialized_definition(
    *,
    plan: Any,
    case: Any,
    qa_phase: str,
    baseline: Optional[str],
    baseline_position: int,
    transition_id: Optional[str],
    execution_target: Optional[Mapping[str, Any]] = None,
    target_env: Optional[str] = None,
) -> dict[str, Any]:
    """Every column this plan case materializes onto one requirement row.

    ``execution_target`` is optional because it is not the plan case's to
    decide: a writer resolves it from the plan's environment or from the
    target a run already froze, and passes it in. A caller that only wants to
    know what the case itself says omits it, and the two target columns are
    then absent rather than guessed.
    """
    method_config = require_runnable_case(case)
    definition: dict[str, Any] = {
        "qa_kind": "plan_case",
        "qa_phase": str(qa_phase),
        "blocking_mode": "blocking",
        "requirement_source": "flow_derived",
        "success_policy": _success_policy(plan, case),
        "capability_requirements": encoded_capability_kinds(
            materialized_capability_kinds(
                case["required_capability_kinds"], method_config
            ),
            subject=f"plan case {case['case_key']!r}",
        ),
        "plan_id": int(plan["id"]),
        "plan_case_key": str(case["case_key"]),
        "case_position": int(case["position"]),
        "baseline_position": int(baseline_position),
        "method_id": str(case["method_id"]),
        "method_name": str(case["method_name"]),
        "runner_id": str(case["runner_id"]),
        "verdict_path": str(case["verdict_path"]),
        "host_baseline": baseline,
        "starting_state": case.get("starting_state"),
        "starting_state_reason": case.get("starting_state_reason"),
        "entry_surface": case["entry_surface"],
        "required_completion": case["required_completion"],
        "workflow_transition_id": transition_id,
        "instructions": str(case["instructions"]),
        "expected_outcome": str(case["expected_outcome"]),
        "method_config": _json(method_config),
    }
    from yoke_core.domain.qa_plan_case_targets import (
        case_target_envs,
        case_applies_to_target,
    )

    if execution_target is not None and not case_applies_to_target(
        case, execution_target
    ):
        raise QaPlanError(
            f"case_target_not_selected: case {case['case_key']!r} does not name "
            "this execution environment. Select the case on a matching QA stage."
        )
    if target_env is None and execution_target is not None and case_target_envs(case):
        target_env = str((execution_target.get("environment") or {}).get("name") or "")
    definition["target_env"] = target_env
    if execution_target is not None:
        definition["execution_target_json"] = canonical_target(execution_target)
        definition["execution_target_digest"] = target_digest(execution_target)
    return definition


def case_target_subject(case: Any, definition: Mapping[str, Any]) -> dict[str, Any]:
    """The case shape :func:`require_case_target` validates, from a definition.

    The target check reads the executable fields it is about to freeze, so it
    reads them from the derivation rather than from the raw case row — the two
    can differ, and the frozen row is the one that matters.
    """
    return {
        "method_id": case["method_id"],
        "instructions": case["instructions"],
        "expected_outcome": case["expected_outcome"],
        "method_config": json.loads(str(definition["method_config"])),
        "entry_surface": case["entry_surface"],
    }


def plan_cases(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    """Every case of this plan, joined to the method that supplies its runner.

    The join is what makes ``method_name`` / ``runner_id`` / ``verdict_path``
    available at all; both rematerialize paths and the drift reader need the
    identical projection, so it is written once here. Each case also carries
    ``materialized_baselines``, its row fan-out, and a plan with a machine-run
    case that declares no starting state is refused here, before any writer
    can mint a requirement that would run on whatever the machine holds.
    """
    from yoke_contracts.qa_case_starting_state import (
        StartingStateError,
        chain_baselines,
    )
    from yoke_core.domain.db_helpers import query_rows
    from yoke_core.domain.qa_plan_management import _placeholder

    rows = [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT c.*, p.slug AS plan_slug, m.name AS method_name, "
            "m.runner_id, m.required_capability_kinds, m.verdict_path, "
            "m.config_contract_id "
            "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
            "JOIN qa_plans p ON p.id=c.plan_id "
            f"WHERE c.plan_id={_placeholder(conn)} ORDER BY c.position",
            (int(plan_id),),
        )
    ]
    try:
        fan_out = chain_baselines(
            [
                {
                    **row,
                    "host_baselines": json.loads(str(row["host_baselines"] or "[]")),
                }
                for row in rows
            ]
        )
    except StartingStateError as exc:
        slug = rows[0]["plan_slug"] if rows else plan_id
        raise QaPlanError(f"QA plan {slug!r} cannot materialize: {exc}") from exc
    for row in rows:
        row["materialized_baselines"] = fan_out[str(row["case_key"])]
    return rows


def snapshot_fan_out(
    plan: Mapping[str, Any], cases: list[Mapping[str, Any]]
) -> dict[str, list[Optional[str]]]:
    """Each case's row fan-out for a deployment run's frozen plan snapshot.

    A snapshot frozen before cases declared a starting state carries none, so
    it is refused with the way forward rather than run on whatever the
    machine holds.
    """
    from yoke_contracts.qa_case_starting_state import (
        StartingStateError,
        chain_baselines,
    )

    try:
        return chain_baselines(cases)
    except StartingStateError as exc:
        raise QaPlanError(
            f"QA plan {plan.get('slug') or plan.get('id')!r} snapshot cannot "
            f"materialize: {exc}. A deployment run freezes its plans when it "
            "is created, so a run frozen before the plan declared its starting "
            "states needs a new deployment run after the plan is corrected"
        ) from exc


def case_baselines(case: Any) -> list[Optional[str]]:
    """The host baselines this case's rows run on, always at least one.

    A ``baseline`` case fans out across its declared baselines; an
    ``inherit`` case follows its predecessor's fan-out, so each of its rows
    names the baseline its chain started from; an ``as_is`` or non-machine
    case materializes exactly one row with ``host_baseline`` NULL.
    """
    return list(case["materialized_baselines"])


__all__ = [
    "case_baselines",
    "case_target_subject",
    "materialized_definition",
    "plan_cases",
    "require_runnable_case",
    "snapshot_fan_out",
]
