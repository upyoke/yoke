"""Preview source-dependent delivery facts, then apply them without source I/O."""

from __future__ import annotations
from dataclasses import dataclass, replace
import json
from typing import Any
from yoke_core.domain.deployment_run_carried_enrollment import CarriedEnrollment
from yoke_core.domain.deployment_run_carried_membership import (
    apply_carried_enrollment,
    enroll_carried_members,
    project_carried_sets,
)
from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
    parse_carried_work,
)
from yoke_core.domain.deployment_run_bound_sources import bound_project_shas
from yoke_core.domain.deployment_run_composition_guard import has_frozen_composition
from yoke_core.domain.deployment_member_snapshot_write import (
    store_member_snapshots,
    write_member_snapshots,
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


def revalidate_bound_source_composition(
    conn, run_id, record, project_ids, preview, *, current=False
):
    """Reject raced landings, then reread mutable facts using prepared sources.

    *current* says the caller proved, under the run lock, that nothing the
    preview read has changed; the preview then stands without a reread.
    """
    if preview.containment is not None:
        basis = candidate_containment_basis(conn, run_id, bound_sources=record)
        if basis["basis_digest"] != preview.containment["basis_digest"]:
            raise CandidateContainmentRefusal(
                "candidate_containment_attestation_stale",
                f"candidate attribution changed while preparing {run_id}",
                f"re-drive {run_id} to prepare the current landing facts",
            )
    if current:
        return preview
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


@dataclass(frozen=True)
class PlannedRecomposition:
    """A recomposition judged before the run lock, for the record being bound.

    ``snapshots`` are the frozen run's new members' rows, as
    ``(selections, snapshots, requirement_ids, plan_ids)``; ``verdict`` is the
    composition judgement ``cmd_validate_composition`` would give after the
    writes. ``further`` is the enrollment that judgement would make of the
    carried items outside the rebound projects; its reads are covered by the
    rebound enrollment's basis, so confirming that one confirms both.
    """

    snapshots: tuple[dict, dict, tuple[int, ...], tuple[int, ...]] | None
    verdict: tuple[bool, str]
    further: CarriedEnrollment | None = None

    @property
    def row_ids(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """The requirement and plan rows this plan read unlocked."""
        requirements, plans = set(), set()
        if self.snapshots is not None:
            requirements.update(self.snapshots[2])
            plans.update(self.snapshots[3])
        if self.further is not None and self.further.admission is not None:
            requirements.update(self.further.admission.requirement_ids)
            plans.update(self.further.admission.plan_ids)
        return tuple(sorted(requirements)), tuple(sorted(plans))


def plan_recomposition(
    conn: Any,
    run_id: str,
    record: dict[str, Any],
    preview: BoundSourceComposition,
    enrollment: CarriedEnrollment | None,
) -> PlannedRecomposition | None:
    """Judge the recomposed run before the lock, without writing it.

    The judgement reads the rebound *record*, the preview's carried work and
    the rows *enrollment* would insert. ``None`` sends the caller to the
    locked recomposition: a schema or state this pass cannot stand in for.
    """
    from yoke_core.domain.deployment_member_snapshot_write import (
        read_member_snapshots,
        snapshot_row_ids,
    )
    from yoke_core.domain.deployment_run_carried_membership import (
        carried_enrollment_blocked,
        plan_carried_enrollment,
    )
    from yoke_core.domain.deployment_run_project_sources import (
        proposed_run_source_facts,
    )
    from yoke_core.domain.deployment_run_proposed_membership import (
        proposed_membership,
    )
    from yoke_core.domain.deployment_runs_validation import judge_composition
    from yoke_core.domain.schema_read_scope import reads_active

    if not reads_active() or (enrollment is not None and enrollment.refusal):
        return None
    rows = dict(enrollment.proposed_rows) if enrollment is not None else {}
    snapshots = None
    if has_frozen_composition(conn, run_id):
        if conn.execute(
            "SELECT 1 FROM deployment_run_items WHERE run_id=%s "
            "AND COALESCE(requirement_snapshot,'')='' LIMIT 1",
            (run_id,),
        ).fetchone():
            return None
        stored = {
            item_id: row["requirement_selection"] for item_id, row in rows.items()
        }
        selections, frozen = read_member_snapshots(conn, run_id, stored, lock=False)
        snapshots = (selections, frozen, *snapshot_row_ids(selections, frozen))
        for item_id in rows:
            rows[item_id] = dict(
                rows[item_id],
                requirement_selection=selections[item_id],
                requirement_snapshot=frozen[item_id],
            )
    project_id = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    with (
        proposed_membership(conn, run_id, rows),
        proposed_run_source_facts(conn, run_id, dumps_compact(record)),
    ):
        carried = further = None
        if not carried_enrollment_blocked(conn, run_id):
            carried = preview.carried
            try:
                further = plan_carried_enrollment(
                    conn, run_id, carried_work=carried, custody=preview.custody
                )
            except (LookupError, ValueError):
                # The locked judgement reports this refusal in its own words.
                return None
    if further is not None and further.refusal is not None:
        return None
    rows.update(further.proposed_rows if further is not None else {})
    with (
        proposed_membership(conn, run_id, rows),
        proposed_run_source_facts(conn, run_id, dumps_compact(record)),
    ):
        verdict = judge_composition(
            conn,
            run_id,
            int(project_id),
            errors=[],
            enrolled=further.refs if further is not None else (),
            carried=carried,
            custody=preview.custody,
            enrollment_error=None,
            allow_pending_pair_merges=False,
            composition_result=None,
            require_item_qa_members=True,
        )
    return PlannedRecomposition(snapshots, verdict, further)


def recompose_bound_sources(
    conn: Any,
    run_id: str,
    project_ids: frozenset[int],
    preview: BoundSourceComposition,
    *,
    enrollment: CarriedEnrollment | None = None,
    planned: PlannedRecomposition | None = None,
) -> None:
    """Keep existing contracts and admit newly carried work in the transaction.

    *enrollment* is the decision made before the run lock and confirmed under
    it; without one, enrollment decides here. *planned*, judged with it before
    the lock, replaces the locked snapshot reads and composition judgement.
    """
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
        enrollment=enrollment,
    )
    if planned is not None:
        if planned.snapshots is not None:
            store_member_snapshots(conn, run_id, *planned.snapshots[:2])
        valid, reason = planned.verdict
        if planned.further is not None:
            outcome = apply_carried_enrollment(
                conn, run_id, replace(planned.further, confirmed=True)
            )
            if not outcome.as_planned or outcome.error is not None:
                valid, reason = cmd_validate_composition(
                    run_id, connection=conn, custody=preview.custody
                )
    else:
        rows = (
            conn.execute(
                "SELECT item_id,requirement_selection FROM deployment_run_items WHERE run_id=%s AND COALESCE(requirement_snapshot,'')=''",
                (run_id,),
            ).fetchall()
            if has_frozen_composition(conn, run_id)
            else ()
        )
        write_member_snapshots(conn, run_id, {int(row[0]): row[1] for row in rows})
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
