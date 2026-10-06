"""Which post-deploy obligations a membership row takes on for its item.

A post_deploy requirement is answered by the admitted copy the deployment
run froze for it, and by nothing else. So a membership that selected
nothing selected no obligations either: the run ships the item's code,
its QA stage finds no member obligation to materialize, and the item's
``done`` transition then blocks forever on rows no run will ever admit.

Admission therefore derives the selection rather than waiting to be told.
An item's outstanding obligations are the unwaived, unsuperseded, unretracted,
run-unbound ``post_deploy`` rows it still owes -- plan-backed and ad-hoc
method rows alike -- and the ones this run can discharge are those whose
``target_env`` a QA stage on its pinned flow actually targets. An explicit
operator selection is still honoured verbatim; derivation fills the silence
that used to mean "nothing".

The filter here is deliberately the permissive half of the pair.
:func:`yoke_core.domain.deployment_qa_frozen_plan_selection.requirement_applies`
re-filters the frozen snapshot against the target the stage actually
observed, so selecting a row a run-preview stage *might* answer costs
nothing, while dropping it would lose the obligation silently.

What no stage on the run can discharge is never dropped quietly:
:func:`unadmitted_post_deploy_notice` names those rows, their declared
environment, and the stage targets the run does have, on the composition
answer and on the membership add that missed them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Iterable, Sequence

from yoke_core.domain.deployment_flow_policy import STAGE_KIND_QA
from yoke_core.domain.deployment_run_composition_freeze import (
    member_ids,
    requires_release_admission,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql
from yoke_core.domain.schema_common import _column_exists, _table_exists

POST_DEPLOY_PHASE = "post_deploy"

UNADMITTED_RECOVERY = (
    "No QA stage on this run targets them, so the run will freeze no "
    "admitted copy and the item's done transition keeps blocking. Correct "
    "whichever of the two is wrong -- the requirement's target_env (yoke qa "
    "requirement update --requirement-id N --field target_env --value ENV) "
    "or the flow's QA stage target -- deliver the item through a flow whose "
    "stage target matches, or waive the requirement through the registered "
    "waiver surface with explicit authorization."
)


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def run_qa_stage_targets(conn: Any, run_id: str) -> tuple[frozenset[str], bool]:
    """Environment names this run's QA stages target, and whether any is dynamic.

    A ``run_preview`` stage names its environment only in the receipt it has
    not produced yet, so it reports as dynamic rather than as a name: nothing
    can be ruled out against a target nobody has observed.
    """
    row = conn.execute(
        "SELECT df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (str(run_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    try:
        stages = json.loads(str(_cell(row, "stages", 0) or "[]"))
    except (TypeError, ValueError) as exc:
        raise ValueError("deployment flow stages are invalid JSON") from exc
    environments: set[str] = set()
    dynamic = False
    for stage in stages:
        if not isinstance(stage, Mapping) or stage.get("stage_kind") != STAGE_KIND_QA:
            continue
        target = stage.get("target")
        if not isinstance(target, Mapping):
            continue
        if target.get("kind") == "persistent_environment":
            name = str(target.get("environment") or "").strip()
            if name:
                environments.add(name)
        else:
            dynamic = True
    return frozenset(environments), dynamic


def stage_target_admits(
    target_env: Any, *, environments: frozenset[str], dynamic: bool
) -> bool:
    """Whether a run with these QA stage targets can discharge this row.

    An undeclared ``target_env`` takes whichever target the stage observes,
    matching the frozen-snapshot filter, so it needs a QA stage and nothing
    more. A declared one needs that environment, or a dynamic target that
    could still turn out to be it.
    """
    if not environments and not dynamic:
        return False
    declared = str(target_env or "").strip()
    return not declared or dynamic or declared in environments


def requirement_target_environment(target_env: Any, execution_target_json: Any) -> str:
    """A named case target or the immutable destination of a plan-backed case."""
    declared = str(target_env or "").strip()
    if declared or not execution_target_json:
        return declared
    target = (
        dict(execution_target_json)
        if isinstance(execution_target_json, Mapping)
        else json.loads(str(execution_target_json))
    )
    return str((target.get("environment") or {}).get("name") or "")


def outstanding_post_deploy_requirements(
    conn: Any, item_id: int
) -> tuple[dict[str, Any], ...]:
    """Outstanding intake for one item, using the shared set reader."""
    return outstanding_post_deploy_requirement_sets(conn, (item_id,)).get(item_id, ())


def outstanding_post_deploy_requirement_sets(
    conn: Any, item_ids: Sequence[int]
) -> dict[int, tuple[dict[str, Any], ...]]:
    """Read unwaived, unsuperseded intake and withdrawn plans in one query."""
    if not item_ids or not _table_exists(conn, "qa_requirements"):
        return {}
    supersession = (
        " AND r.superseded_by_requirement_id IS NULL"
        if _column_exists(conn, "qa_requirements", "superseded_by_requirement_id")
        else ""
    )
    target_column = (
        "r.execution_target_json"
        if _column_exists(conn, "qa_requirements", "execution_target_json")
        else "NULL"
    )
    withdrawn = ""
    if _column_exists(conn, "qa_plan_item_attachments", "retracted_at"):
        withdrawn = (
            " AND NOT EXISTS (SELECT 1 FROM qa_plan_item_attachments a "
            "WHERE a.item_id=r.item_id AND a.plan_id=r.plan_id "
            "AND a.qa_phase='post_deploy' AND a.retracted_at IS NOT NULL)"
        )
    rows = conn.execute(
        f"SELECT r.item_id,r.id,r.target_env,{target_column} FROM qa_requirements r "
        f"WHERE r.item_id IN ({','.join('%s' for _ in item_ids)}) "
        "AND r.qa_phase='post_deploy' AND r.deployment_run_id IS NULL AND r.waived_at IS NULL"
        f"{supersession}{withdrawn} AND {unretracted_requirement_sql(conn, 'r')} ORDER BY r.id",
        tuple(int(value) for value in item_ids),
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row[0]), []).append(
            {
                "id": int(row[1]),
                "target_env": requirement_target_environment(row[2], row[3]),
            }
        )
    return {item_id: tuple(requirements) for item_id, requirements in grouped.items()}


def post_deploy_admission_split(
    conn: Any, *, run_id: str, item_id: int
) -> tuple[tuple[int, ...], tuple[dict[str, Any], ...]]:
    """Split one item's outstanding obligations into admitted and unreachable.

    A flow predating release admission freezes no member snapshot at all, so
    it derives nothing and reports nothing: there is no admitted copy for a
    selection to become.
    """
    if not requires_release_admission(conn, run_id):
        return (), ()
    environments, dynamic = run_qa_stage_targets(conn, run_id)
    admitted: list[int] = []
    unadmitted: list[dict[str, Any]] = []
    from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run

    supplemental = supplemental_qa_run(conn, run_id=run_id, item_id=item_id)
    for row in outstanding_post_deploy_requirements(conn, int(item_id)):
        if supplemental and not row["target_env"]:
            continue
        if stage_target_admits(
            row["target_env"], environments=environments, dynamic=dynamic
        ):
            admitted.append(row["id"])
        else:
            unadmitted.append(row)
    return tuple(admitted), tuple(unadmitted)


def admissible_post_deploy_requirement_ids(
    conn: Any, *, run_id: str, item_id: int
) -> tuple[int, ...]:
    """The requirement ids a silent membership selection should carry."""
    admitted, _ = post_deploy_admission_split(conn, run_id=run_id, item_id=int(item_id))
    return admitted


def unadmitted_post_deploy_notice(
    conn: Any, run_id: str, *, item_ids: Sequence[int] | None = None
) -> str:
    """Name every member obligation no stage target on this run can discharge."""
    if not requires_release_admission(conn, run_id):
        return ""
    subjects: Iterable[int] = (
        member_ids(conn, run_id)
        if item_ids is None
        else tuple(int(v) for v in item_ids)
    )
    from yoke_core.domain.deployment_run_member_targeting import (
        companion_requirement_sets,
        supplemental_item_ids,
    )
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows

    subjects = tuple(subjects)
    requirements = outstanding_post_deploy_requirement_sets(conn, subjects)
    companions = companion_requirement_sets(conn, run_id=run_id, item_ids=subjects)
    supplemental = supplemental_item_ids(
        conn, run_id=run_id, completion_flows=item_completion_flows(conn, subjects)
    )
    environments, dynamic = run_qa_stage_targets(conn, run_id)
    labels: list[str] = []
    for item_id in subjects:
        for row in requirements.get(item_id, ()):
            if (
                item_id in supplemental and not row["target_env"]
            ) or stage_target_admits(
                row["target_env"], environments=environments, dynamic=dynamic
            ):
                continue
            if row["id"] in companions.get(item_id, ()):
                continue
            declared = row["target_env"] or "(none declared)"
            labels.append(
                f"{render_item_ref(conn, int(item_id))} requirement #{row['id']} (target_env={declared})"
            )
    if not labels:
        return ""
    targets = ", ".join(sorted(environments)) or "none"
    if dynamic:
        targets += " plus a run-preview target resolved at execution"
    return (
        f"Unadmitted post-deploy obligation(s): {', '.join(labels)}; this "
        f"run's QA stage targets are {targets}. {UNADMITTED_RECOVERY}"
    )


__all__ = [
    "POST_DEPLOY_PHASE",
    "UNADMITTED_RECOVERY",
    "admissible_post_deploy_requirement_ids",
    "outstanding_post_deploy_requirements",
    "post_deploy_admission_split",
    "run_qa_stage_targets",
    "stage_target_admits",
    "unadmitted_post_deploy_notice",
]
