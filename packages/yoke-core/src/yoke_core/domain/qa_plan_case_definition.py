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
        "entry_surface": case["entry_surface"],
        "required_completion": case["required_completion"],
        "workflow_transition_id": transition_id,
        "instructions": str(case["instructions"]),
        "expected_outcome": str(case["expected_outcome"]),
        "method_config": _json(method_config),
    }
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


def plan_cases(conn: Any, plan_id: int) -> list[Any]:
    """Every case of this plan, joined to the method that supplies its runner.

    The join is what makes ``method_name`` / ``runner_id`` / ``verdict_path``
    available at all; both rematerialize paths and the drift reader need the
    identical projection, so it is written once here.
    """
    from yoke_core.domain.db_helpers import query_rows
    from yoke_core.domain.qa_plan_management import _placeholder

    return query_rows(
        conn,
        "SELECT c.*, m.name AS method_name, m.runner_id, "
        "m.required_capability_kinds, m.verdict_path, m.config_contract_id "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={_placeholder(conn)} ORDER BY c.position",
        (int(plan_id),),
    )


def case_baselines(case: Any) -> list[Optional[str]]:
    """The host baselines this case fans out across, always at least one.

    A case with no declared baseline still materializes exactly one row, with
    ``host_baseline`` NULL — so the plan-to-row fan-out is total and the
    comparison never has a case with no row to be behind.
    """
    declared = json.loads(str(case["host_baselines"] or "[]"))
    return list(declared) if declared else [None]


__all__ = [
    "case_baselines",
    "case_target_subject",
    "materialized_definition",
    "plan_cases",
    "require_runnable_case",
]
