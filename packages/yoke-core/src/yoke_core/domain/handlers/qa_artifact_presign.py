"""``qa.artifact.presign`` — server-minted S3 PUT URLs for QA evidence.

The browser-QA orchestrator runs wherever evidence is captured. A local or
self-hosted server signs with its configured ``aws-admin`` capability. A
hosted tenant instead uses the token-authenticated Platform broker published
through ``YOKE_QA_ARTIFACT_BROKER_URL``; the tenant never receives AWS
credentials. Both return the exact ``artifact_handle`` the client records via
``qa.artifact.add`` after its plain HTTPS PUT succeeds.

Bucket resolution order: the requirement's declared ``target_env`` when
that environment declares a bucket, else ``prod``, else the remaining
environments name-sorted. No environment declaring a bucket is the sole
``s3_not_configured`` result; byte-submission callers then let
``qa.artifact.add`` persist the evidence in the server's permanent local
application-data tree. Direct stores may set ``artifacts.prefix``; hosted
tenants receive their immutable prefix with the broker settings.
"""

from __future__ import annotations

from yoke_core.domain.qa_artifact_configuration import (
    resolve_artifacts_bucket as resolve_artifacts_bucket,
    _aws_region as _aws_region,
    _capability_credentials as _capability_credentials,
)

from typing import Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
from yoke_core.domain.qa_artifact_storage import ARTIFACT_PRESIGN_EXPIRES_S
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

PRESIGN_EXPIRES_S = ARTIFACT_PRESIGN_EXPIRES_S

_NO_BUCKET_REMEDIATION = (
    "no environment of project {project!r} declares an artifacts bucket; "
    "apply the environment stack, record its artifactsBucketName through "
    "the project environment-settings artifacts.bucket surface, or submit "
    "the artifact bytes "
    "through qa.artifact.add for permanent server-local storage"
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


def handle_qa_artifact_presign(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        build_artifact_key,
        s3_handle,
    )
    from yoke_core.domain.qa_artifacts import case_artifact_subject
    from yoke_core.domain.qa_artifact_broker import (
        ArtifactBrokerError,
        broker_config,
        presign_with_broker,
    )
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
        try:
            req_row = requirement_storage_owner(conn, int(req_id))
        except LookupError as exc:
            return _error("not_found", str(exc))
        except ValueError as exc:
            return _error("target_invalid", str(exc))
        project = str(req_row["project"])
        subject = case_artifact_subject(dict(req_row))

        try:
            resolved = resolve_artifacts_bucket(
                conn,
                int(req_row["project_id"]),
                req_row["target_env"],
            )
        except ArtifactBrokerError as exc:
            return _error(exc.code, str(exc))
        except ValueError as exc:
            return _error("s3_configuration_invalid", str(exc))
        if resolved is None:
            return _error(
                "s3_not_configured",
                _NO_BUCKET_REMEDIATION.format(project=project),
            )
        env_name, bucket, storage_prefix = resolved
        try:
            broker = broker_config()
        except ArtifactBrokerError as exc:
            return _error(exc.code, str(exc))
        region = (
            None
            if broker is not None
            else _aws_region(conn, int(req_row["project_id"]))
        )
        if broker is None and not region:
            return _error(
                "s3_configuration_invalid",
                f"project {project!r} declares artifacts bucket {bucket!r} "
                "but its aws-admin capability has no region; set the "
                "capability region",
            )
    finally:
        conn.close()

    if broker is not None:
        try:
            signed = presign_with_broker(
                broker,
                operation="put",
                project=project,
                subject=subject,
                run_id=int(run_id),
                filename=filename,
            )
            handle = s3_handle(signed.bucket, signed.key, content_type=content_type)
        except (ArtifactBrokerError, ArtifactHandleError, ValueError) as exc:
            code = getattr(exc, "code", "payload_invalid")
            return _error(code, str(exc), jsonpath="$.payload.filename")
        return HandlerOutcome(
            result_payload={
                "upload_url": signed.url,
                "artifact_handle": handle,
                "expires_in_s": signed.expires_in,
                "environment": env_name,
            },
            primary_success=True,
        )

    credentials = _capability_credentials(project)
    if credentials is None:
        return _error(
            "s3_configuration_invalid",
            f"project {project!r} declares artifacts bucket {bucket!r} but "
            "its aws-admin capability secrets are missing (need "
            "access_key_id + secret_access_key); store them via "
            "`yoke projects capability secret set --project "
            f"{project} --cap-type aws-admin --key access_key_id VALUE` "
            "and `--key secret_access_key VALUE`",
        )

    try:
        key = build_artifact_key(
            project,
            subject,
            int(run_id),
            filename,
            storage_prefix=storage_prefix,
        )
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
