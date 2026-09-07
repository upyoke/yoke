"""``qa.artifact.presign`` — server-minted S3 PUT URLs for QA evidence.

The browser-QA orchestrator runs on whatever machine captures the
evidence; the dispatcher (in-process or behind the https relay) is where
project AWS authority lives. This handler keeps that split honest: the
server resolves the project environment's artifacts bucket
(``environments.settings.artifacts.bucket``) and the ``aws-admin``
capability credentials, mints a SigV4 presigned PUT URL, and returns it
together with the exact ``artifact_handle`` the client must record via
``qa.artifact.add`` after the upload succeeds. The client needs no AWS
credentials — the upload is one plain HTTPS PUT.

Bucket resolution order: the requirement's declared ``target_env`` when
that environment declares a bucket, else ``prod``, else the remaining
environments name-sorted. No environment declaring a bucket is a typed
``s3_not_configured`` error — callers then record an explicit ``local``
handle (durability is opt-in; local capture stays the default).
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

PRESIGN_EXPIRES_S = 900

_NO_BUCKET_REMEDIATION = (
    "no environment of project {project!r} declares an artifacts bucket; "
    "apply the environment stack (output artifactsBucketName) and record "
    "it: python3 -m yoke_core.domain.projects environment-merge-settings "
    "<env-id> --set artifacts.bucket=<name>. Until then record an explicit "
    "local artifact_handle instead."
)


class QaArtifactPresignRequest(BaseModel):
    run_id: int
    filename: str
    content_type: Optional[str] = None


class QaArtifactPresignResponse(BaseModel):
    upload_url: str
    artifact_handle: dict
    expires_in_s: int
    environment: str


def resolve_artifacts_bucket(
    conn,
    project_id: int,
    target_env: Optional[str],
) -> Optional[Tuple[str, str]]:
    """Return ``(env_name, bucket)`` for the project, or ``None``.

    Reads ``environments.settings.artifacts.bucket`` directly on the
    handler's connection (single three-column read; the full renderer
    settings loader opens its own connection and resolves capabilities
    this path does not need).
    """
    p = _p(conn)
    rows = conn.execute(
        "SELECT e.name, e.settings FROM environments e "
        "JOIN sites s ON s.id = e.site "
        f"WHERE s.project_id = {p}",
        (int(project_id),),
    ).fetchall()
    buckets: Dict[str, str] = {}
    for row in rows:
        name, raw = str(row[0]), row[1]
        try:
            settings = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        artifacts = settings.get("artifacts")
        bucket = artifacts.get("bucket") if isinstance(artifacts, dict) else None
        if isinstance(bucket, str) and bucket.strip():
            buckets[name] = bucket.strip()
    if not buckets:
        return None
    order: List[str] = []
    if target_env:
        order.append(str(target_env))
    order.append("prod")
    order.extend(sorted(buckets))
    for name in order:
        if name in buckets:
            return name, buckets[name]
    return None


def _aws_region(conn, project_id: int) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id = {p} AND type = 'aws-admin'",
        (int(project_id),),
    ).fetchone()
    if row is None:
        return None
    try:
        settings = json.loads(str(row[0]) or "{}")
    except ValueError:
        return None
    region = settings.get("region")
    return str(region) if isinstance(region, str) and region.strip() else None


def _capability_credentials(project: str):
    """Resolve aws-admin capability credentials (never ambient shell)."""
    from yoke_core.domain.projects_capabilities import (
        cmd_capability_get_secret,
    )
    from yoke_core.domain.s3_presign import AwsCredentials

    access_key = cmd_capability_get_secret(project, "aws-admin", "access_key_id")
    secret_key = cmd_capability_get_secret(project, "aws-admin", "secret_access_key")
    if not access_key or not secret_key:
        return None
    return AwsCredentials(
        access_key_id=access_key.strip(),
        secret_access_key=secret_key.strip(),
        session_token=(
            cmd_capability_get_secret(project, "aws-admin", "session_token") or None
        ),
    )


def handle_qa_artifact_presign(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        build_artifact_key,
        s3_handle,
    )
    from yoke_core.domain.qa_artifacts import case_artifact_subject
    from yoke_core.domain.s3_presign import presign_s3_url

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.artifact.presign requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    run_id = payload.get("run_id")
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid",
            "run_id is required",
            jsonpath="$.payload.run_id",
        )
    if not isinstance(filename, str) or not filename:
        return _error(
            "payload_invalid",
            "filename is required",
            jsonpath="$.payload.filename",
        )

    conn = connect()
    try:
        p = _p(conn)
        run_row = query_one(
            conn,
            f"SELECT qa_requirement_id FROM qa_runs WHERE id = {p}",
            (int(run_id),),
        )
        if run_row is None:
            return _error("not_found", f"run {run_id} not found")
        if int(run_row["qa_requirement_id"]) != int(req_id):
            return _error(
                "target_invalid",
                f"run {run_id} belongs to requirement "
                f"{run_row['qa_requirement_id']}, not {req_id}",
            )
        # A requirement is owned by an item or by a deployment run, and the
        # project follows whichever one it is. Resolving through the item
        # alone refused every run-owned requirement as "not item-backed",
        # which is how a deployment run's QA gate ended up unable to store
        # the evidence its approver was being asked to judge.
        req_row = query_one(
            conn,
            "SELECT r.item_id, r.epic_id, r.task_num, r.deployment_run_id, "
            "r.target_env, COALESCE(i.project_id, d.project_id) AS project_id, "
            "p.slug AS project "
            "FROM qa_requirements r "
            "LEFT JOIN items i ON i.id = r.item_id "
            "LEFT JOIN deployment_runs d ON d.id = r.deployment_run_id "
            "LEFT JOIN projects p "
            "ON p.id = COALESCE(i.project_id, d.project_id) "
            f"WHERE r.id = {p}",
            (int(req_id),),
        )
        if req_row is None:
            return _error("not_found", f"requirement {req_id} not found")
        # Epic-task requirements are the third owner kind, and durable
        # storage has no key layout for them: naming that is the refusal,
        # rather than reporting a project the row does not have.
        if req_row["project"] is None:
            return _error(
                "target_invalid",
                f"requirement {req_id} resolves to no project through its "
                f"owner (item_id={req_row['item_id']!r}, "
                f"epic_id={req_row['epic_id']!r}, "
                f"deployment_run_id={req_row['deployment_run_id']!r}); "
                "presigned evidence upload resolves the project through an "
                "item-owned or deployment-run-owned requirement, so record "
                "an explicit local artifact_handle instead",
            )
        project = str(req_row["project"])
        subject = case_artifact_subject(dict(req_row))

        resolved = resolve_artifacts_bucket(
            conn,
            int(req_row["project_id"]),
            req_row["target_env"],
        )
        if resolved is None:
            return _error(
                "s3_not_configured",
                _NO_BUCKET_REMEDIATION.format(project=project),
            )
        env_name, bucket = resolved
        region = _aws_region(conn, int(req_row["project_id"]))
        if not region:
            return _error(
                "s3_not_configured",
                f"project {project!r} aws-admin capability declares no "
                "region; set it via python3 -m yoke_core.domain.projects "
                f"capability-merge-settings {project} aws-admin "
                "--set region=<aws-region>",
            )
    finally:
        conn.close()

    credentials = _capability_credentials(project)
    if credentials is None:
        return _error(
            "s3_not_configured",
            f"project {project!r} aws-admin capability secrets are missing "
            "(need access_key_id + secret_access_key); store them locally via "
            "`yoke projects capability secret set --project "
            f"{project} --cap-type aws-admin --key access_key_id VALUE` "
            "and `--key secret_access_key VALUE`",
        )

    try:
        key = build_artifact_key(project, subject, int(run_id), filename)
        handle = s3_handle(bucket, key, content_type=content_type)
    except (ArtifactHandleError, ValueError) as exc:
        return _error(
            "payload_invalid",
            str(exc),
            jsonpath="$.payload.filename",
        )
    upload_url = presign_s3_url(
        method="PUT",
        bucket=bucket,
        key=key,
        region=region,
        credentials=credentials,
        expires_s=PRESIGN_EXPIRES_S,
    )
    return HandlerOutcome(
        result_payload={
            "upload_url": upload_url,
            "artifact_handle": handle,
            "expires_in_s": PRESIGN_EXPIRES_S,
            "environment": env_name,
        },
        primary_success=True,
    )


__all__ = [
    "PRESIGN_EXPIRES_S",
    "QaArtifactPresignRequest",
    "QaArtifactPresignResponse",
    "handle_qa_artifact_presign",
    "resolve_artifacts_bucket",
]
