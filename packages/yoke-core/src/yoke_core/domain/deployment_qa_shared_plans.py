"""Plan subjects shared by members shipping the same source to the same target."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_qa_shared_plan_reads import (
    attaching_members,
    _member_attached_plan_ids,
    _other_members_plan_ids,
    _formed_group_plan_ids,
)
from yoke_core.domain.qa_execution_environment_target import canonical_target


def shared_subject(subject: Mapping, target: Mapping, snapshot: Mapping) -> dict:
    """Keep plan identity, never an attaching member, in the execution target."""
    plan = snapshot["plan"]
    identity = {
        "plan_id": int(plan["id"]),
        "source_revision": plan.get("source_revision"),
    }
    normalized = deepcopy(dict(target))
    normalized["deployment"].pop("member_item_id", None)
    normalized["deployment"]["shared_plan"] = identity
    return {
        **subject,
        "member_item_id": None,
        "member_snapshot": None,
        "shared_plan": identity,
        "shared_snapshot": dict(snapshot),
        "shared_target": normalized,
    }


def shareable_snapshots(
    conn: Any,
    subject: Mapping,
    target: Mapping,
    snapshots: list[dict],
    *,
    projection=None,
) -> list[dict]:
    """Share attached plans with peers, or keep an already formed group shared."""
    if projection is not None:
        return projection.shareable(subject, target, snapshots)
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        stage_environment_id_for_plan_selection,
    )

    member = subject.get("member_item_id")
    if member is None:
        return []
    environment_id = stage_environment_id_for_plan_selection(conn, target)
    ids = _member_attached_plan_ids(
        conn, int(member), subject.get("member_snapshot"), target, environment_id
    ) & (
        _other_members_plan_ids(
            conn, str(subject["id"]), int(member), target, environment_id
        )
        | _formed_group_plan_ids(
            conn, str(subject["id"]), str(subject["stage"]["name"])
        )
    )
    return [snapshot for snapshot in snapshots if int(snapshot["plan"]["id"]) in ids]


def member_plan_subjects(
    conn: Any, subject: Mapping, target: Mapping, *, projection=None
) -> list[dict]:
    """The plan verdicts this member owes, without other members' plans."""
    if subject.get("member_item_id") is None:
        return []
    from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
    from yoke_core.domain.deployment_qa_plan_selection import selected_plans

    admitted = member_requirements(conn, subject, target=target)
    snapshots = selected_plans(
        conn,
        subject,
        agent_plan=None,
        target=target,
        admitted=admitted,
        allow_empty=True,
        lock_plans=False,
    )
    return [
        shared_subject(subject, target, snapshot)
        for snapshot in shareable_snapshots(
            conn, subject, target, snapshots, projection=projection
        )
    ]


def resolve_shared_subject(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    plan_id: int,
    member_item_id: int | None = None,
    expected_target: Mapping | None = None,
    require_active: bool = True,
) -> dict:
    """Resolve a shared group only through a member that actually selected it."""
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )

    matches = {}
    for member in attaching_members(conn, run_id, int(plan_id), member_item_id):
        subject = deployment_qa_stage_subject(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member,
            require_active=require_active,
        )
        if subject["stage"]["scope"] != "item":
            break
        target = deployment_qa_execution_target(conn, subject)
        for group in member_plan_subjects(conn, subject, target):
            if group["shared_plan"]["plan_id"] != int(plan_id):
                continue
            resolved = deployment_qa_execution_target(conn, group)
            if expected_target is not None and canonical_target(
                resolved
            ) != canonical_target(expected_target):
                continue
            # An exact frozen target names one equivalence class. Finding an
            # attaching member proves it; unrelated peers add no authority.
            if expected_target is not None:
                return group
            matches[canonical_target(resolved)] = group
    if len(matches) != 1:
        raise ValueError(
            f"shared_plan_subject_unresolved: plan {plan_id} has {len(matches)} matching "
            f"groups in run {run_id} stage {stage_name}; select an attaching --item "
            "to disambiguate, or restore its plan attachment and current producer receipt"
        )
    return next(iter(matches.values()))


def frozen_shared_target(conn: Any, subject: Mapping) -> dict:
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    return presentation_read(
        conn,
        ("qa_shared_target", canonical_target(subject["shared_target"])),
        lambda: _read_frozen_shared_target(conn, subject),
    )


def _read_frozen_shared_target(conn: Any, subject: Mapping) -> dict:
    """Freeze endpoints per group while its exact producer receipt is current."""
    import json

    target = dict(subject["shared_target"])
    from yoke_core.domain.deployment_qa_presentation_facts import (
        subject_requirement_rows,
    )

    rows = subject_requirement_rows(conn, subject["id"], subject["stage"]["name"], None)
    if rows is not None:
        rows = [
            row
            for row in rows
            if row["plan_id"] == subject["shared_plan"]["plan_id"]
            and row["deployment_member_item_id"] is None
        ]
    else:
        rows = query_rows(
            conn,
            "SELECT execution_target_json FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND deployment_member_item_id IS NULL AND plan_id=%s ORDER BY id",
            (
                subject["id"],
                subject["stage"]["name"],
                subject["shared_plan"]["plan_id"],
            ),
        )
    for row in rows:
        raw = row["execution_target_json"]
        frozen = dict(raw) if isinstance(raw, Mapping) else json.loads(str(raw))
        if all(
            frozen.get(key) == target.get(key)
            for key in ("tenant", "project", "observation", "deployment")
        ):
            return frozen
    return target


def execution_subject(
    conn: Any, execution: Mapping, *, require_active: bool = True
) -> dict:
    """Recover a private or shared subject from its immutable execution target."""
    import json

    from yoke_core.domain.qa_request_subjects import execution_subject_once
    from yoke_core.domain.deployment_qa_takeover_identity import read_execution_subject

    target = (
        execution.get("execution_target")
        or execution.get("execution_target_json")
        or {}
    )
    if not isinstance(target, Mapping):
        target = json.loads(str(target))
    return execution_subject_once(
        execution,
        target,
        require_active=require_active,
        read=lambda active: read_execution_subject(
            conn, execution, target, require_active=active
        ),
    )


def requirement_subject(
    conn: Any, requirement_id: int, *, require_active: bool = True
) -> dict:
    """Resolve stage policy and target authority from a stored requirement."""
    rows = query_rows(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,execution_target_json "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if not rows:
        raise ValueError(
            "shared_plan_requirement_missing: inspect the requirement id before retrying"
        )
    return execution_subject(conn, rows[0], require_active=require_active)


def group_members(conn: Any, subject: Mapping, target: Mapping) -> list[int]:
    """Only members selecting this exact plan/source/target receive its verdict."""
    return _group_members(conn, subject, target, run_id=str(subject["id"]))


@presentation_operation
@run_presentation
def _group_members(conn: Any, subject: Mapping, target: Mapping, *, run_id: str):
    # Each member's check resolves its siblings' plans; one presentation of
    # the run reads those once for every member instead of once per member.
    plan_id = int(subject["shared_plan"]["plan_id"])
    found = []
    for member in attaching_members(conn, run_id, plan_id):
        try:
            resolve_shared_subject(
                conn,
                run_id=subject["id"],
                stage_name=subject["stage"]["name"],
                plan_id=plan_id,
                member_item_id=member,
                expected_target=target,
                require_active=False,
            )
        except ValueError:
            continue
        found.append(member)
    return found


def member_group_digests(conn: Any, run_id: str, stage: str, member: int) -> set[str]:
    """Resolve ownership once per member during a read-only presentation."""
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    return set(
        presentation_read(
            conn,
            ("qa_member_group_digests", run_id, stage, member),
            lambda: _read_member_group_digests(conn, run_id, stage, member),
        )
    )


def _read_member_group_digests(conn, run_id, stage, member):
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.qa_execution_environment_target import target_digest

    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=stage,
        member_item_id=member,
        require_active=False,
    )
    target = deployment_qa_execution_target(conn, subject)
    return {
        target_digest(deployment_qa_execution_target(conn, group))
        for group in member_plan_subjects(conn, subject, target)
    }


def shared_target_identity(raw: Any) -> Mapping | None:
    """Recognize only explicit shared groups when reading run-wide history."""
    import json

    try:
        target = raw if isinstance(raw, Mapping) else json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(target, Mapping):
        return None
    return (target.get("deployment") or {}).get("shared_plan")
