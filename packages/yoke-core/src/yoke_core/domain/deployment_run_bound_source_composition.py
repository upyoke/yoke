"""Preview source-dependent delivery facts, then apply them without source I/O."""

from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any
from yoke_core.domain.deployment_run_carried_membership import (
    enroll_carried_members,
    project_carried_sets,
)
from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
    parse_carried_work,
)
from yoke_core.domain.deployment_run_bound_sources import bound_project_shas
from yoke_core.domain.deployment_run_composition_guard import has_frozen_composition
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    candidate_custody,
    CustodyResolution,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.deployment_run_contained_items import (
    candidate_containment_basis,
    CandidateContainmentRefusal,
    record_attested_candidate_containment,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    CandidateContainment,
)
from yoke_core.domain.json_helper import dumps_compact


@dataclass(frozen=True)
class BoundSourceComposition:
    """A source walk's facts held for the candidate being bound."""

    carried: dict[str, Any]
    custody: CustodyResolution
    lock_item_ids: list[int]
    containment: dict[str, Any] | None


def preview_bound_source_composition(
    conn: Any, run_id: str, record: dict[str, Any], project_ids: frozenset[int]
) -> BoundSourceComposition:
    """Resolve network facts before any item/run write lock is taken."""
    return _read_composition(conn, run_id, record, project_ids)


def revalidate_bound_source_composition(conn, run_id, record, project_ids, preview):
    """Reject raced landings, then reread mutable facts using prepared sources."""
    if preview.containment is not None:
        basis = candidate_containment_basis(conn, run_id, bound_sources=record)
        if basis["basis_digest"] != preview.containment["basis_digest"]:
            raise CandidateContainmentRefusal(
                "candidate_containment_attestation_stale",
                f"candidate attribution changed while preparing {run_id}",
                f"re-drive {run_id} to prepare the current landing facts",
            )
    return _read_composition(conn, run_id, record, project_ids)


def _read_composition(conn, run_id, record, project_ids):
    stored = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    carried = derive_carried_work_safely(
        conn, run_id, bound_sources=record, preserved_work=parse_carried_work(stored)
    )
    for project in project_carried_sets(carried):
        if not (project.get("derivation") or {}).get("contents_known"):
            derivation = project.get("derivation") or {}
            raise ValueError(
                f"bound_source_composition_unverified: {derivation.get('reason')}; {derivation.get('recovery')}; re-drive {run_id}"
            )
    custody = CustodyResolution(
        conn,
        run_id,
        candidate=candidate_custody(
            conn, run_id, source_shas=bound_project_shas(record)
        ),
    )
    members = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    ids = {int(row[0]) for row in members}
    ids.update(custody.enrollable)
    ids.update(
        int(item["item_id"])
        for project in project_carried_sets(carried)
        for item in project.get("items") or []
    )
    containment = _preview_containment(
        conn, run_id, record, project_ids, {int(row[0]) for row in members}
    )
    return BoundSourceComposition(carried, custody, sorted(ids), containment)


def _preview_containment(
    conn: Any,
    run_id: str,
    record: dict[str, Any],
    project_ids: frozenset[int],
    members: set[int],
) -> dict[str, Any] | None:
    stored = conn.execute(
        "SELECT candidate_containment FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    if not stored:
        return None
    previous = json.loads(str(stored))
    basis = candidate_containment_basis(conn, run_id, bound_sources=record)
    old = {
        (int(a["project_id"]), int(a["id"]), a["candidate_lineage"], a["merge_sha"]): a
        for a in previous.get("answers") or []
    }
    answers = []
    for project in basis["projects"]:
        pid, lineage = int(project["project_id"]), str(project["candidate_lineage"])
        walk = CandidateContainment(conn, pid, candidate_lineage=lineage)
        for item in project.get("items") or []:
            key = (pid, int(item["id"]), lineage, str(item["merge_sha"]))
            answer = old.get(key)
            if answer is None:
                verdict = walk.contains(key[3])
                if verdict.state not in {CONTAINED, NOT_CONTAINED}:
                    raise ValueError(
                        f"bound_source_containment_unverified: {item['public_ref']}: {verdict.reason}; {verdict.recovery}; re-drive {run_id}"
                    )
                answer = dict(
                    project_id=pid,
                    id=key[1],
                    candidate_lineage=lineage,
                    merge_sha=key[3],
                    state=verdict.state,
                    source=verdict.source,
                )
            if (
                pid in project_ids
                and key[1] in members
                and answer["state"] != CONTAINED
            ):
                raise ValueError(
                    f"bound_source_excludes_member: {item['public_ref']} is outside {lineage}; restore consumer main to a containing revision, then re-drive {run_id}"
                )
            answers.append(answer)
    return {"basis_digest": basis["basis_digest"], "answers": answers}


def recompose_bound_sources(
    conn: Any, run_id: str, project_ids: frozenset[int], preview: BoundSourceComposition
) -> None:
    """Keep existing contracts and admit newly carried work in the transaction."""
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (dumps_compact(preview.carried), run_id),
    )
    enroll_carried_members(
        conn,
        run_id,
        carried_work=preview.carried,
        custody=preview.custody,
        rebound_project_ids=project_ids,
    )
    if has_frozen_composition(conn, run_id):
        rows = conn.execute(
            "SELECT item_id,requirement_selection FROM deployment_run_items WHERE run_id=%s AND COALESCE(requirement_snapshot,'')=''",
            (run_id,),
        ).fetchall()
        for row in rows:
            item_id = int(row[0])
            selection = row[1] or requirement_selection(
                requirement_ids=admissible_post_deploy_requirement_ids(
                    conn, run_id=run_id, item_id=item_id
                )
            )
            snapshot = snapshot_member_requirements(
                conn, run_id=run_id, item_id=item_id, selection_json=selection
            )
            conn.execute(
                "UPDATE deployment_run_items SET requirement_selection=%s,requirement_snapshot=%s WHERE run_id=%s AND item_id=%s",
                (selection, snapshot, run_id, item_id),
            )
    valid, reason = cmd_validate_composition(
        run_id, connection=conn, custody=preview.custody
    )
    if not valid:
        raise ValueError(
            f"bound_source_composition_invalid: {reason}; repair the named obligation, then re-drive {run_id}"
        )
    if preview.containment is not None:
        conn.execute(
            "UPDATE deployment_runs SET candidate_containment=NULL WHERE id=%s",
            (run_id,),
        )
        record_attested_candidate_containment(conn, run_id, preview.containment)
