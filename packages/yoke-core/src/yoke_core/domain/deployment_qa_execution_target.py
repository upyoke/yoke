"""Observed deployment target binding for scoped QA execution and results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.machine_qa_case_target import DEPLOYMENT_TARGET_SCHEMA
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_release_version import pinned_release_endpoints
from yoke_core.domain.deployment_qa_target_project import target_project
from yoke_core.domain.deployment_stage_receipts import deployment_stage_receipt_for_qa
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    environment_row_endpoints,
)


from yoke_core.domain.deployment_qa_target_reads import (
    first_materialized_execution_target,
    _latest_ready_receipt_id,
)
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

DEPLOYMENT_TARGET_KIND = "deployment"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row(cursor: Any, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "keys"):
        return {str(key): value[key] for key in value.keys()}
    names = [str(getattr(col, "name", None) or col[0]) for col in cursor.description]
    return dict(zip(names, value, strict=True))


def _read_persistent_target(
    conn: Any, project_id: int, environment: str, run_id: str
) -> dict:
    def read():
        cursor = conn.execute(
            "SELECT e.id AS environment_id,e.name AS environment_name,e.url,e.settings,"
            "s.name AS site_name FROM environments e JOIN sites s ON s.id=e.site "
            f"WHERE s.project_id={_p(conn)} AND e.name={_p(conn)}",
            (project_id, environment),
        )
        return _row(cursor, cursor.fetchone())

    row = presentation_read(conn, ("qa_environment_row", project_id, environment), read)
    if row is None:
        raise ValueError(
            f"deployment_member_target_missing: project {project_id} has no registered "
            f"QA target environment {environment!r}; register the deployed environment "
            "for that project before starting QA"
        )
    return {
        "environment": {
            "id": int(row["environment_id"]),
            "name": environment,
            "kind": "persistent_environment",
        },
        "site": {"name": str(row["site_name"])},
        "endpoints": pinned_release_endpoints(
            conn, run_id, project_id, environment_row_endpoints(row)
        ),
    }


def _persistent_target(conn, project_id, environment, run_id):
    return presentation_read(
        conn,
        ("qa_persistent_target", run_id, project_id, environment),
        lambda: _read_persistent_target(conn, project_id, environment, run_id),
    )


def _preview_target(receipt: Mapping[str, Any]) -> dict:
    url = str(receipt.get("observed_url") or "").strip().rstrip("/")
    if not url:
        raise ValueError(
            "ready run-preview receipt has no observed URL; repair the producer "
            "receipt before starting QA"
        )
    name = str(receipt["target_name"])
    return {
        "environment": {"name": name, "kind": "run_preview"},
        "site": {"name": name},
        "endpoints": {"app_url": url, "api_url": url},
        "observed_url": url,
    }


def _frozen_producer_receipt_id(target: Mapping[str, Any]) -> int | None:
    observation = target.get("observation")
    if not isinstance(observation, Mapping) or observation.get("receipt_id") is None:
        return None
    return int(observation["receipt_id"])


def _require_receipt_source(subject: Mapping[str, Any], source_stage: str) -> None:
    stages = subject["stages"]
    qa_name = str(subject["stage"]["name"])
    names = [
        str(stage.get("name") or "") if isinstance(stage, Mapping) else ""
        for stage in stages
    ]
    if source_stage not in names or qa_name not in names:
        raise ValueError("deployment QA receipt source is not pinned by the flow")
    if names.index(source_stage) >= names.index(qa_name):
        raise ValueError("deployment QA receipt source must precede the QA stage")
    source = stages[names.index(source_stage)]
    if (
        not isinstance(source, Mapping)
        or source.get("stage_kind") == "qa"
        or source.get("step_runner") == "qa"
    ):
        raise ValueError("deployment QA receipt source must be a non-QA stage")


def deployment_qa_execution_target(conn: Any, subject: Mapping[str, Any]) -> dict:
    """Resolve configured destination plus the newest observed stage receipt.

    After this subject has materialized at least one case, later reads
    reuse that snapshot while the producer receipt is unchanged, so a live
    environment edit cannot move the digest mid-stage; a newer ready
    receipt is a new identity resolved live.
    """
    if subject.get("shared_plan"):
        from yoke_core.domain.deployment_qa_shared_plans import frozen_shared_target

        return frozen_shared_target(conn, subject)
    project = target_project(conn, subject)
    frozen = first_materialized_execution_target(
        conn,
        run_id=str(subject["id"]),
        stage_name=str(subject["stage"]["name"]),
        member_item_id=subject.get("member_item_id"),
    )
    from yoke_core.domain.deployment_qa_takeover_identity import inherited_target

    if (
        frozen is not None
        and (frozen.get("project") or {}).get("id") == project["id"]
        and inherited_target(conn, str(subject["id"]), frozen)
    ):
        return frozen
    pinned = subject["stage"].get("target")
    source_stage = (
        str(pinned.get("source_stage") or "").strip()
        if isinstance(pinned, Mapping)
        else ""
    )
    latest_receipt = (
        _latest_ready_receipt_id(conn, run_id=str(subject["id"]), source_stage=source_stage)
        if source_stage
        else None
    )
    frozen_receipt = _frozen_producer_receipt_id(frozen) if frozen is not None else None
    if (
        frozen is not None
        and latest_receipt is not None
        and frozen_receipt is not None
        and latest_receipt == frozen_receipt
        and (frozen.get("project") or {}).get("id") == project["id"]
    ):
        return frozen
    target = subject["stage"].get("target")
    if not isinstance(target, Mapping):
        raise ValueError("deployment QA stage has no pinned target")
    kind = str(target.get("kind") or "")
    source_stage = str(target.get("source_stage") or "").strip()
    if not source_stage:
        raise ValueError(
            "deployment QA target has no receipt-producing source_stage; update "
            "the disabled flow definition before execution"
        )
    _require_receipt_source(subject, source_stage)
    expected_name = (
        str(target.get("environment") or "")
        if kind == "persistent_environment"
        else None
    )
    receipt = presentation_read(
        conn,
        (
            "qa_producer_receipt",
            str(subject["id"]),
            source_stage,
            kind,
            expected_name,
            str(subject["release_lineage"]),
            str(subject.get("artifact_identity")),
        ),
        lambda: deployment_stage_receipt_for_qa(
            conn,
            run_id=str(subject["id"]),
            source_stage=source_stage,
            expected_target_kind=kind,
            expected_target_name=expected_name,
            expected_release_lineage=str(subject["release_lineage"]),
            expected_artifact_identity=subject.get("artifact_identity"),
        ),
    )
    identity = {
        "tenant": {
            "id": int(subject["tenant_id"]),
            "slug": str(subject["tenant_slug"]),
            "name": str(subject["tenant_name"]),
        },
        "project": project,
        "observation": {
            "receipt_id": int(receipt["id"]),
            "source_stage": source_stage,
            "attempt_number": int(receipt["attempt_number"]),
            "correlation_id": str(receipt["correlation_id"]),
            "observed_release_lineage": str(receipt["observed_release_lineage"]),
            "observed_artifact_identity": receipt.get("observed_artifact_identity"),
        },
        "deployment": {
            "run_id": str(subject["id"]),
            "stage": str(subject["stage"]["name"]),
            "member_item_id": subject.get("member_item_id"),
            "release_lineage": str(subject["release_lineage"]),
            "artifact_identity": subject.get("artifact_identity"),
        },
    }
    if kind == "persistent_environment":
        resolved = _persistent_target(
            conn, project["id"], expected_name or "", str(subject["id"])
        )
        observed_url = str(receipt.get("observed_url") or "").rstrip("/")
        configured_urls = {
            str(value).rstrip("/")
            for key, value in resolved["endpoints"].items()
            if key.endswith("_url") and value
        }
        if observed_url and configured_urls and observed_url not in configured_urls:
            raise ValueError(
                "deployment_member_target_missing: deployment stage receipt URL "
                "does not match the configured environment endpoint; execute a "
                "producer stage that observes this project's deployed target"
            )
        resolved["observed_url"] = observed_url or None
    elif kind == "run_preview":
        resolved = _preview_target(receipt)
    else:
        raise ValueError("deployment QA stage target kind is unsupported")
    return {
        "schema": DEPLOYMENT_TARGET_SCHEMA,
        "target_kind": DEPLOYMENT_TARGET_KIND,
        **identity,
        **resolved,
    }


def is_deployment_execution_target(target: Mapping[str, Any]) -> bool:
    return (
        target.get("schema") == DEPLOYMENT_TARGET_SCHEMA
        and target.get("target_kind") == DEPLOYMENT_TARGET_KIND
    )


#: Which release, source and receipt a target was frozen from. QA tests
#: whatever is deployed, so a successor or newer receipt never gates a write.
_SOURCE_KEYS = frozenset({"run_id", "release_lineage", "artifact_identity"})


def _destination(target: Mapping[str, Any]) -> str:
    """Tenant, project, subject and endpoints, without release provenance."""
    from yoke_core.domain.deployment_qa_release_version import RELEASE_VERSION_KEY

    deployment = target.get("deployment") or {}
    endpoints = target.get("endpoints") or {}
    return canonical_target(
        {
            **{k: v for k, v in target.items() if k != "observation"},
            "deployment": {k: v for k, v in deployment.items() if k not in _SOURCE_KEYS},
            "endpoints": {k: v for k, v in endpoints.items() if k != RELEASE_VERSION_KEY},
        }
    )


def validate_deployment_execution_target(
    conn: Any, execution: Mapping[str, Any], *, require_active: bool = True
) -> None:
    """Reject cancelled, detached or cross-subject result writes.

    The subject read owns run, stage, member, ownership and cancellation
    authority. The target must still name the subject's tenant, project and
    endpoints; which release, source or receipt it was frozen from is
    provenance and never refuses a write.
    """
    from yoke_core.domain.deployment_qa_shared_plans import execution_subject

    subject = execution_subject(conn, execution, require_active=require_active)
    actual = execution.get("execution_target")
    expected = deployment_qa_execution_target(conn, subject)
    if not isinstance(actual, Mapping) or _destination(actual) != _destination(
        expected
    ):
        raise ValueError(
            "qa_execution_destination_mismatch: this execution's target names "
            "another tenant, project, subject or endpoint than its current "
            "owner; preserve this evidence and inspect the execution's recorded "
            "target"
        )


__all__ = [
    "DEPLOYMENT_TARGET_KIND",
    "DEPLOYMENT_TARGET_SCHEMA",
    "deployment_qa_execution_target",
    "first_materialized_execution_target",
    "is_deployment_execution_target",
    "validate_deployment_execution_target",
]
