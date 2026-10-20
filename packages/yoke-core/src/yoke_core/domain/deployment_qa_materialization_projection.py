"""Run-wide shared-group facts one QA write reads before the run row lock."""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)


@dataclass(frozen=True)
class SharedGroup:
    """One shared plan group a member selects, with its resolved target."""

    subject: dict
    target: dict
    plan_id: int
    canonical: str
    digest: str
    # resolve_shared_subject only lets a member of the plan's project attach.
    same_project: bool


class MaterializationProjection:
    """Selection facts for one run, read once; never requirements or outcomes.

    Read it inside a ``presentation_operation`` over the run's members so
    every per-member question is one set read. The fingerprint comes first,
    so ``holds`` under the run lock proves every later read is still current.
    """

    def __init__(self, conn, run_id):
        self.conn = conn
        self.run_id = str(run_id)
        self.fingerprint = run_qa_fingerprint(conn, self.run_id)
        self._members = None
        self._selections = {}
        self._groups = {}

    def holds(self, conn) -> bool:
        """Whether nothing this projection read changed; call under the run lock."""
        return run_qa_fingerprint(conn, self.run_id) == self.fingerprint

    def members(self):
        if self._members is None:
            self._members = query_rows(
                self.conn,
                "SELECT m.item_id,m.requirement_snapshot,i.project_id "
                "FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
                "WHERE m.run_id=%s ORDER BY m.item_id",
                (self.run_id,),
            )
        return self._members

    def shareable(self, subject, target, snapshots):
        from yoke_core.domain.deployment_qa_shared_plans import (
            _formed_group_plan_ids,
            _member_attached_plan_ids,
        )
        from yoke_core.domain.qa_deployment_member_attached_plans import (
            stage_environment_id_for_plan_selection,
        )

        member = subject.get("member_item_id")
        if member is None:
            return []
        stage_name = str(subject["stage"]["name"])
        environment_id = stage_environment_id_for_plan_selection(self.conn, target)
        key = (
            stage_name,
            environment_id,
            (target.get("environment") or {}).get("name"),
        )
        if key not in self._selections:
            selected = {}
            for row in self.members():
                raw = row["requirement_snapshot"]
                snapshot = (
                    raw if isinstance(raw, Mapping) else json.loads(str(raw or "{}"))
                )
                selected[int(row["item_id"])] = _member_attached_plan_ids(
                    self.conn, int(row["item_id"]), snapshot, target, environment_id
                )
            counts = Counter(plan for plans in selected.values() for plan in plans)
            formed = _formed_group_plan_ids(self.conn, self.run_id, stage_name)
            self._selections[key] = {
                owner: {plan for plan in plans if counts[plan] > 1 or plan in formed}
                for owner, plans in selected.items()
            }
        ids = self._selections[key].get(int(member), set())
        return [
            snapshot for snapshot in snapshots if int(snapshot["plan"]["id"]) in ids
        ]

    def stage_groups(self, stage_name):
        """Each member's shared groups at one stage, or the error resolving it."""
        from yoke_core.domain.deployment_qa_stage_contract import (
            deployment_qa_stage_subject,
        )
        from yoke_core.domain.deployment_qa_execution_target import (
            deployment_qa_execution_target,
        )
        from yoke_core.domain.deployment_qa_shared_plans import member_plan_subjects

        stage_name = str(stage_name)
        if stage_name in self._groups:
            return self._groups[stage_name]
        groups = {}
        for row in self.members():
            member = int(row["item_id"])
            try:
                subject = deployment_qa_stage_subject(
                    self.conn,
                    run_id=self.run_id,
                    stage_name=stage_name,
                    member_item_id=member,
                    require_active=False,
                )
                member_target = deployment_qa_execution_target(self.conn, subject)
                selected = member_plan_subjects(
                    self.conn, subject, member_target, projection=self
                )
                resolved = []
                for group in selected:
                    target = deployment_qa_execution_target(self.conn, group)
                    plan = group["shared_snapshot"]["plan"]
                    resolved.append(
                        SharedGroup(
                            subject=group,
                            target=target,
                            plan_id=int(plan["id"]),
                            canonical=canonical_target(target),
                            digest=target_digest(target),
                            same_project=int(plan["project_id"])
                            == int(row["project_id"]),
                        )
                    )
                groups[member] = resolved
            except (LookupError, ValueError) as exc:
                groups[member] = exc
        self._groups[stage_name] = groups
        return groups

    def member_groups(self, stage_name, member):
        """The member's groups, raising the error that resolving them raised."""
        groups = self.stage_groups(stage_name).get(int(member), [])
        if isinstance(groups, Exception):
            raise groups
        return groups

    def digests(self, stage_name, member):
        return {group.digest for group in self.member_groups(stage_name, member)}

    def group_members(self, subject, target):
        """Members attaching this exact group; unresolvable members attach none."""
        canonical = canonical_target(target)
        return [
            member
            for member, groups in self.stage_groups(subject["stage"]["name"]).items()
            if not isinstance(groups, Exception)
            and any(g.same_project and g.canonical == canonical for g in groups)
        ]

    def attached(self, stage_name, plan_id, *, without, target=None):
        """Whether a member outside ``without`` still attaches the plan's group.

        A remaining member whose groups cannot be resolved may attach it, so
        that error is raised rather than answering ``False``.
        """
        canonical = canonical_target(target) if target is not None else None
        unreadable = None
        for member, groups in self.stage_groups(stage_name).items():
            if member in without:
                continue
            if isinstance(groups, Exception):
                unreadable = unreadable or groups
                continue
            if any(
                g.same_project
                and g.plan_id == int(plan_id)
                and (canonical is None or g.canonical == canonical)
                for g in groups
            ):
                return True
        if unreadable is not None:
            raise unreadable
        return False


def read_run_projection(conn, *, run_id, stages):
    """A projection with these stages' groups read now, as one set per fact.

    For writers that consult groups later, under the run lock: everything
    they ask was read here, before it.
    """
    from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
    from yoke_core.domain.deployment_qa_presentation_reads import (
        presentation_operation,
    )

    @presentation_operation
    @run_presentation
    def read(conn, *, run_id):
        projection = MaterializationProjection(conn, run_id)
        for stage_name in sorted({str(stage) for stage in stages}):
            projection.stage_groups(stage_name)
        return projection

    return read(conn, run_id=str(run_id))
