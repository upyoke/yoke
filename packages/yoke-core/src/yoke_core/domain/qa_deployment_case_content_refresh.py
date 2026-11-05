"""Compare executable case content and correct only the lineage head."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdict,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_requirement_pass_currency import executable_method_config
from yoke_core.domain.qa_requirement_lineage import (
    base_case_key,
    head_owes_work,
    rows_by_case,
)


#: The fields that decide what a runner will actually do. Anything outside
#: this set may differ without making the frozen row the wrong case.
_CONTENT_FIELDS = (
    "method_id",
    "method_config",
    "instructions",
    "expected_outcome",
)

#: Separates a corrected case's key from the content digest that makes it
#: distinct. Chosen because no authored case key may contain it.
REFRESH_KEY_SEPARATOR = "@"

_DIGEST_LENGTH = 12


def _normalized(value: Any) -> Any:
    """Compare stored JSON text and decoded payloads as the same content."""
    # Typed execution configs may serialize an integer timeout as a float.
    # Its numeric value has not changed, so neither has executable content.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): _normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "["):
            try:
                return _normalized(json.loads(text))
            except (TypeError, ValueError):
                return value
        return value
    return value


def case_content_digest(case: Mapping[str, Any]) -> str:
    """Stable identity for the executable content of one case.

    ``method_config`` is compared in its executable form: the in-place
    correction marker a requirement update stamps on a row is not content,
    and counting it made a corrected-but-current row read as changed.
    """
    payload = {field: _normalized(case.get(field)) for field in _CONTENT_FIELDS}
    if isinstance(payload["method_config"], Mapping):
        payload["method_config"] = executable_method_config(payload["method_config"])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def plan_case_content_digest(conn: Any, case: Mapping[str, Any]) -> str:
    """Identity of a plan case as it materializes, not as it was stored.

    A stored plan case keeps the form the build that wrote it produced; its
    copies hold the form the materializing build's validator returns. Deriving
    the case through that same validator first makes the two comparable
    whatever release stored the plan. A case read without its method's
    contract takes it from the method catalog, as plan case reads do.
    """
    from yoke_core.domain.db_helpers import query_scalar
    from yoke_core.domain.qa_plan_case_definition import require_runnable_case

    contract = case.get("config_contract_id") or query_scalar(
        conn,
        "SELECT config_contract_id FROM qa_methods WHERE id=%s",
        (str(case["method_id"]),),
    )
    if not contract:
        raise QaPlanError(
            f"case {case.get('case_key')!r}: method {case['method_id']!r} is not "
            "registered, so its content cannot be compared; register the method "
            "or correct the plan case."
        )
    derived = {**case, "config_contract_id": str(contract)}
    return case_content_digest(
        {**case, "method_config": require_runnable_case(derived)}
    )


def refreshed_case_key(plan_case_key: str, digest: str) -> str:
    """The key a corrected case materializes under, beside the frozen row."""
    return f"{base_case_key(plan_case_key)}{REFRESH_KEY_SEPARATOR}{digest}"


def refreshed_case_keys(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    plan_id: int,
    execution_target_digest: str,
    group_id: str = "",
    cases: list[Mapping[str, Any]],
    explicitly_replaced: frozenset[int] = frozenset(),
) -> dict[tuple[str, Any], str]:
    """Map each case key that needs a fresh row to the key it takes.

    Empty when every case is either still answered by its row or unchanged
    since it was materialized -- which is the ordinary idempotent outcome.
    Refuses, before anything is written, when a row nobody has judged still
    stands for a case whose content has since moved: no fresh row may compete
    with it, and walking it as it stands would judge against content the
    plan replaced. The refusal names the refresh that brings it current.

    A case whose failed row is being replaced explicitly (``--replaces``, in
    this call or an earlier one) gets no automatic row: the named corrected
    case already carries that attempt, and a second, automatic one would
    compete with it (:func:`carried_by_declared_replacement`).
    """
    by_key = rows_by_case(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        plan_id=plan_id,
        group_id=group_id,
    )
    refreshed = {}
    behind = []
    for case in cases:
        key = str(case["case_key"])
        digest = plan_case_content_digest(conn, case)
        for (authored, baseline), heads in by_key.items():
            if authored != key:
                continue
            for head in heads:
                # A correction can only be created by the head's own plan.
                if int(head["plan_id"]) != int(plan_id):
                    continue
                if case_content_digest(head) == digest:
                    continue
                if int(head["id"]) in explicitly_replaced:
                    continue
                if head_owes_work(conn, head):
                    refreshed[(key, baseline)] = refreshed_case_key(key, digest)
                elif not determinate_verdict(conn, int(head["id"])) and not any(
                    head.get(field) for field in ("waived_at", "retracted_at")
                ):
                    behind.append(int(head["id"]))
    if behind:
        raise QaPlanError(_behind_plan_refusal(conn, plan_id, behind))
    return refreshed


def _behind_plan_refusal(conn: Any, plan_id: int, requirement_ids: list[int]) -> str:
    from yoke_core.domain.qa_plan_case_currency import STALE_PLAN_CASE_CODE
    from yoke_core.domain.qa_plan_rematerialize import refresh_recovery

    row = query_rows(
        conn,
        "SELECT id,item_id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,plan_id,execution_target_json,qa_phase,"
        "workflow_transition_id FROM qa_requirements WHERE id=%s",
        (requirement_ids[0],),
    )[0]
    ids = ", ".join(str(requirement_id) for requirement_id in requirement_ids)
    return (
        f"{STALE_PLAN_CASE_CODE}: QA requirement {ids} has not been judged, and "
        f"its case in QA plan {plan_id} has changed since it was materialized. "
        "Running it would judge against a definition the plan has already "
        f"replaced. {refresh_recovery(conn, row)} Then run the stage again."
    )


def declare_refreshed_replacements(conn: Any, created_ids: list[int]) -> None:
    """Declare each fresh corrected row the replacement of the rows it corrects.

    A refreshed row exists only because every earlier row for its case and
    baseline stopped answering; the ones that failed without being settled
    are exactly the attempts it now carries. They keep blocking until it
    passes (:mod:`qa_requirement_replacement`).
    """
    from yoke_core.domain.qa_requirement_replacement import point_at_replacement

    for created_id in created_ids:
        fresh = query_rows(
            conn,
            "SELECT id,plan_case_key,deployment_run_id,deployment_stage,"
            "deployment_member_item_id,plan_id,execution_target_json,"
            "host_baseline FROM qa_requirements WHERE id=%s",
            (int(created_id),),
        )
        if not fresh or REFRESH_KEY_SEPARATOR not in str(fresh[0]["plan_case_key"]):
            continue
        row = fresh[0]
        from yoke_core.domain.qa_requirement_lineage import rows_by_case
        from yoke_core.domain.qa_deployment_requirement_identity_schema import (
            shared_group_id,
        )
        import json

        target = row["execution_target_json"]
        target = target if isinstance(target, dict) else json.loads(target)
        groups = rows_by_case(
            conn,
            run_id=row["deployment_run_id"],
            stage_name=row["deployment_stage"],
            member_item_id=row["deployment_member_item_id"],
            plan_id=row["plan_id"],
            group_id=shared_group_id(target),
        )
        for head in groups.get(
            (base_case_key(row["plan_case_key"]), row["host_baseline"]), []
        ):
            if int(head["id"]) != created_id and head_owes_work(conn, head):
                point_at_replacement(conn, int(head["id"]), created_id)


__all__ = [
    "REFRESH_KEY_SEPARATOR",
    "declare_refreshed_replacements",
    "base_case_key",
    "case_content_digest",
    "plan_case_content_digest",
    "refreshed_case_key",
    "refreshed_case_keys",
]
