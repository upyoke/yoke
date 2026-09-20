"""Materialize frozen member QA obligations on their deployment-stage subject."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    require_case_target,
    target_digest,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target
from yoke_core.domain.db_helpers import query_rows

ADMITTED_REQUIREMENT_CASE_PREFIX = "admitted-requirement-"


def admitted_requirement_case_key(source_id: int) -> str:
    """Stable case key for a frozen-admission copy of an intake row."""
    return f"{ADMITTED_REQUIREMENT_CASE_PREFIX}{int(source_id)}"


def admitted_source_requirement_id(case_key: Any) -> int | None:
    """The intake requirement an admitted case key names, or ``None``.

    The inverse of :func:`admitted_requirement_case_key`, and its neighbour
    on purpose: the key is the only link an admitted copy keeps back to the
    row it was frozen from, so both directions live in one place. Every
    other case key -- a plan's own, or ``ad-hoc-`` -- names no source row.
    """
    key = str(case_key or "")
    if not key.startswith(ADMITTED_REQUIREMENT_CASE_PREFIX):
        return None
    tail = key[len(ADMITTED_REQUIREMENT_CASE_PREFIX) :]
    if not tail.isdigit():
        return None
    source_id = int(tail)
    return source_id if source_id > 0 else None


def _target_environment(target: Mapping[str, Any]) -> str:
    environment = target.get("environment")
    if not isinstance(environment, Mapping):
        return ""
    return str(environment.get("name") or "").strip()


def requirement_applies(
    requirement: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Select only post-deploy obligations declared for this destination."""
    if str(requirement.get("qa_phase") or "") != "post_deploy":
        return False
    declared = str(requirement.get("target_env") or "").strip()
    return not declared or declared == _target_environment(target)


def member_requirements(
    subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> list[dict[str, Any]]:
    snapshot = subject.get("member_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    return [
        dict(requirement)
        for requirement in snapshot.get("requirements") or []
        if isinstance(requirement, Mapping) and requirement_applies(requirement, target)
    ]


def _stored_json(value: Any, *, default: Any = None) -> str | None:
    if value in (None, ""):
        value = default
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def materialize_admitted_requirement(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    requirement: Mapping[str, Any],
    target: Mapping[str, Any],
    now: str,
) -> tuple[int, bool]:
    """Copy one frozen obligation without importing its former item subject.

    The copy belongs to no plan, so it stores no ``case_position`` and no
    ``baseline_position``. Only a plan assigns those, and the roster
    selection (:func:`qa_plan_execution_roster.ordered_plan_requirements`)
    gives a plan-less case its order at selection time. Writing numbers
    here would make the row claim an ordering authority nothing declared,
    and the drift check that every execution begin runs
    (:func:`machine_qa_plan_case_snapshot.case_positions`) reads such a
    number as "this requirement joined a plan after the roster froze" and
    refuses the case for good -- a rebuilt roster reads the same row, so
    abort-and-restart cannot clear it either.
    """
    source_id = int(requirement.get("id") or 0)
    if source_id < 1:
        raise QaPlanError("frozen member QA requirement has no source identity")
    case_key = admitted_requirement_case_key(source_id)
    existing = conn.execute(
        "SELECT id,execution_target_json,execution_target_digest "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND plan_id IS NULL "
        "AND plan_case_key=%s AND execution_target_digest=%s ORDER BY id",
        (
            str(subject["id"]),
            str(subject["stage"]["name"]),
            int(subject.get("member_item_id") or 0),
            case_key,
            target_digest(target),
        ),
    ).fetchall()
    if existing:
        ids = require_existing_target(
            [
                {
                    "id": row["id"],
                    "execution_target_json": row["execution_target_json"],
                    "execution_target_digest": row["execution_target_digest"],
                }
                if hasattr(row, "keys")
                else {
                    "id": row[0],
                    "execution_target_json": row[1],
                    "execution_target_digest": row[2],
                }
                for row in existing
            ],
            execution_target=dict(target),
            subject=f"admitted QA requirement {source_id}",
        )
        if len(ids) != 1:
            raise QaPlanError(
                f"admitted QA requirement {source_id} was materialized more than once"
            )
        return ids[0], False

    method_id = str(requirement.get("method_id") or "").strip() or None
    if method_id is not None:
        snapshot_fields = ("method_name", "runner_id", "verdict_path")
        if any(
            not str(requirement.get(field) or "").strip() for field in snapshot_fields
        ):
            raise QaPlanError(
                f"admitted QA requirement {source_id} lacks its frozen method "
                "snapshot; converge requirement snapshots before freezing the run"
            )
        if requirement.get("host_baseline"):
            raise QaPlanError(
                f"admitted QA requirement {source_id} uses a grouped host baseline; "
                "admit its attached plan instead"
            )
        require_case_target(
            {
                "method_id": method_id,
                "instructions": requirement.get("instructions"),
                "expected_outcome": requirement.get("expected_outcome"),
                "method_config": requirement.get("method_config") or {},
                "entry_surface": requirement.get("entry_surface"),
            },
            target,
        )
    columns = (
        "deployment_run_id",
        "deployment_stage",
        "deployment_member_item_id",
        "qa_kind",
        "qa_phase",
        "target_env",
        "blocking_mode",
        "requirement_source",
        "success_policy",
        "capability_requirements",
        "suite_id",
        "plan_case_key",
        "case_position",
        "baseline_position",
        "method_id",
        "method_name",
        "runner_id",
        "verdict_path",
        "host_baseline",
        "entry_surface",
        "required_completion",
        "instructions",
        "expected_outcome",
        "method_config",
        "execution_target_json",
        "execution_target_digest",
        "created_at",
    )
    environment = target.get("environment")
    target_env = environment.get("name") if isinstance(environment, Mapping) else None
    values = (
        str(subject["id"]),
        str(subject["stage"]["name"]),
        subject.get("member_item_id"),
        str(requirement.get("qa_kind") or "release_qa"),
        "post_deploy",
        target_env,
        str(requirement.get("blocking_mode") or "blocking"),
        "flow_derived",
        _stored_json(requirement.get("success_policy")),
        _stored_json(requirement.get("capability_requirements"), default=[]),
        requirement.get("suite_id"),
        case_key,
        None,
        None,
        method_id,
        requirement.get("method_name"),
        requirement.get("runner_id"),
        requirement.get("verdict_path"),
        requirement.get("host_baseline"),
        requirement.get("entry_surface"),
        requirement.get("required_completion"),
        requirement.get("instructions"),
        requirement.get("expected_outcome"),
        _stored_json(requirement.get("method_config"), default={}),
        canonical_target(target),
        target_digest(target),
        now,
    )
    created = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) VALUES "
        f"({','.join('%s' for _ in columns)}) RETURNING id",
        values,
    ).fetchone()
    return int(created["id"] if hasattr(created, "keys") else created[0]), True


def fulfill_admitted_obligations(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_id: str,
    execution_target_digest: str,
    acceptance_qa_kind: str,
) -> list[str]:
    """Require explicit evidence-linked verdicts for aggregate obligations."""
    rows = query_rows(
        conn,
        "SELECT id,qa_kind,waived_at FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND method_id IS NULL "
        "AND qa_kind<>%s AND execution_target_digest=%s ORDER BY id",
        (
            run_id,
            stage_name,
            member_item_id or 0,
            acceptance_qa_kind,
            execution_target_digest,
        ),
    )
    failures: list[str] = []
    for row in rows:
        if row["waived_at"]:
            continue
        latest = conn.execute(
            "SELECT id,verdict,raw_result FROM qa_runs WHERE qa_requirement_id=%s "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (int(row["id"]),),
        ).fetchone()
        if latest is None:
            failures.append(
                f"admitted requirement #{row['id']} has no explicit verdict; "
                "record its evidence-linked result before accepting the stage"
            )
            continue
        verdict = str(
            (latest["verdict"] if hasattr(latest, "keys") else latest[1]) or ""
        )
        if verdict:
            if verdict != "pass":
                failures.append(
                    f"admitted requirement #{row['id']} latest verdict is {verdict}"
                )
                continue
            raw = latest["raw_result"] if hasattr(latest, "keys") else latest[2]
            try:
                evidence = json.loads(str(raw or ""))
            except (TypeError, ValueError):
                evidence = None
            artifact_ids = (
                evidence.get("evidence_artifact_ids")
                if isinstance(evidence, Mapping)
                else None
            )
            if (
                not isinstance(evidence, Mapping)
                or str(evidence.get("execution_id") or "") != execution_id
                or not isinstance(artifact_ids, list)
                or not artifact_ids
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 1
                    for value in artifact_ids
                )
            ):
                failures.append(
                    f"admitted requirement #{row['id']} pass is not linked to "
                    "this execution and concrete evidence artifacts"
                )
                continue
            placeholders = ",".join("%s" for _ in artifact_ids)
            artifact_rows = conn.execute(
                "SELECT DISTINCT a.id FROM qa_artifacts a "
                "JOIN qa_runs r ON r.id=a.qa_run_id "
                "JOIN qa_requirements q ON q.id=r.qa_requirement_id "
                f"WHERE a.id IN ({placeholders}) AND q.deployment_run_id=%s "
                "AND q.deployment_stage=%s "
                "AND COALESCE(q.deployment_member_item_id,0)=%s "
                "AND q.method_id IS NOT NULL",
                (*artifact_ids, run_id, stage_name, member_item_id or 0),
            ).fetchall()
            found = {
                int(value["id"] if hasattr(value, "keys") else value[0])
                for value in artifact_rows
            }
            if found != set(artifact_ids):
                failures.append(
                    f"admitted requirement #{row['id']} references evidence "
                    "outside this deployment QA subject"
                )
            continue
    return failures


__all__ = [
    "ADMITTED_REQUIREMENT_CASE_PREFIX",
    "admitted_requirement_case_key",
    "admitted_source_requirement_id",
    "fulfill_admitted_obligations",
    "materialize_admitted_requirement",
    "member_requirements",
    "requirement_applies",
]
