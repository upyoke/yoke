"""Durable byte storage shared by every QA evidence submission path."""

from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES

from yoke_core.domain import db_backend


ARTIFACT_PRESIGN_EXPIRES_S = 900


class ArtifactStorageError(RuntimeError):
    """A configured artifact store could not durably accept evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def requirement_storage_owner(conn: Any, requirement_id: int) -> dict[str, Any]:
    """Resolve the project and storage subject owning one QA requirement."""

    from yoke_core.domain.db_helpers import query_one

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = query_one(
        conn,
        "SELECT r.item_id, r.epic_id, r.task_num, r.deployment_run_id, "
        "r.target_env, i.project_id AS project_id, "
        "p.slug AS project "
        "FROM qa_requirements r "
        "LEFT JOIN items i ON i.id = r.item_id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE r.id = {marker}",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"requirement {requirement_id} not found")
    owner = dict(row)
    if owner["item_id"] is None and owner["deployment_run_id"] is not None:
        deployment_owner = query_one(
            conn,
            "SELECT d.project_id, p.slug AS project "
            "FROM deployment_runs d "
            "LEFT JOIN projects p ON p.id = d.project_id "
            f"WHERE d.id = {marker}",
            (str(owner["deployment_run_id"]),),
        )
        if deployment_owner is not None:
            owner["project_id"] = deployment_owner["project_id"]
            owner["project"] = deployment_owner["project"]
    if owner["project"] is None:
        raise ValueError(
            f"requirement {requirement_id} resolves to no project through its "
            f"owner (item_id={owner['item_id']!r}, "
            f"epic_id={owner['epic_id']!r}, "
            f"deployment_run_id={owner['deployment_run_id']!r}); durable "
            "evidence requires an item-owned or deployment-run-owned requirement"
        )
    return owner


def _checked_bytes(content: bytes) -> bytes:
    if not content:
        raise ValueError("artifact content is empty")
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"artifact content is {len(content)} bytes; limit is {MAX_ARTIFACT_BYTES}"
        )
    return content


def _write_permanent_local(
    *,
    owner: dict[str, Any],
    run_id: int,
    filename: str,
    content: bytes,
    content_type: Optional[str],
    before_write: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.qa_artifact_handle import local_handle
    from yoke_core.domain.qa_artifacts import (
        case_artifact_subject,
        permanent_artifact_file_path,
    )

    target = permanent_artifact_file_path(
        str(owner["project"]), case_artifact_subject(owner), int(run_id), filename
    )
    if before_write is not None:
        before_write(target)
    handle = tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, target)
    finally:
        if not handle.closed:
            handle.close()
        temporary.unlink(missing_ok=True)
    return local_handle(str(target.resolve()), content_type)


def _upload_bytes(
    upload_url: str,
    *,
    bucket: str,
    key: str,
    content: bytes,
    content_type: Optional[str],
) -> None:
    request = urllib.request.Request(
        upload_url,
        data=content,
        method="PUT",
        headers={"Content-Type": content_type or "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise ArtifactStorageError(
            "s3_upload_failed",
            f"S3 upload failed for s3://{bucket}/{key}: HTTP {exc.code} {exc.reason}",
        ) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ArtifactStorageError(
            "s3_upload_failed",
            f"S3 upload failed for s3://{bucket}/{key}: {exc}",
        ) from exc
    if not 200 <= status < 300:
        raise ArtifactStorageError(
            "s3_upload_failed",
            f"S3 upload failed for s3://{bucket}/{key}: HTTP {status}",
        )


def store_artifact_bytes(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    filename: str,
    content: bytes,
    content_type: Optional[str] = None,
    before_local_write: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Store bytes in configured S3 or permanent server-local storage.

    Only a genuinely absent artifacts bucket selects local storage. Once a
    bucket is configured, missing credentials, invalid configuration, and
    upload failures are explicit errors and never downgrade to disk.
    """

    from yoke_core.domain.handlers.qa_artifact_presign import (
        _aws_region,
        _capability_credentials,
        resolve_artifacts_bucket,
    )
    from yoke_core.domain.qa_artifact_handle import build_artifact_key, s3_handle
    from yoke_core.domain.qa_artifacts import case_artifact_subject
    from yoke_core.domain.qa_artifact_broker import (
        ArtifactBrokerError,
        broker_config,
        presign_with_broker,
    )
    from yoke_core.domain.s3_presign import presign_s3_url

    checked = _checked_bytes(content)
    owner = requirement_storage_owner(conn, requirement_id)
    try:
        configured = resolve_artifacts_bucket(
            conn, int(owner["project_id"]), owner["target_env"]
        )
    except ArtifactBrokerError as exc:
        raise ArtifactStorageError(exc.code, str(exc)) from exc
    except ValueError as exc:
        raise ArtifactStorageError("s3_configuration_invalid", str(exc)) from exc
    if configured is None:
        try:
            return _write_permanent_local(
                owner=owner,
                run_id=run_id,
                filename=filename,
                content=checked,
                content_type=content_type,
                before_write=before_local_write,
            )
        except OSError as exc:
            raise ArtifactStorageError(
                "local_storage_failed",
                f"permanent local artifact storage failed for project "
                f"{owner['project']!r}: {exc}",
            ) from exc

    _environment, bucket, storage_prefix = configured
    project = str(owner["project"])
    subject = case_artifact_subject(owner)
    key = build_artifact_key(
        project, subject, int(run_id), filename, storage_prefix=storage_prefix
    )
    try:
        broker = broker_config()
    except ArtifactBrokerError as exc:
        raise ArtifactStorageError(exc.code, str(exc)) from exc
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
        except ArtifactBrokerError as exc:
            raise ArtifactStorageError(exc.code, str(exc)) from exc
        _upload_bytes(
            signed.url,
            bucket=signed.bucket,
            key=signed.key,
            content=checked,
            content_type=content_type,
        )
        return s3_handle(signed.bucket, signed.key, content_type)
    region = _aws_region(conn, int(owner["project_id"]))
    if not region:
        raise ArtifactStorageError(
            "s3_configuration_invalid",
            f"project {project!r} declares artifacts bucket {bucket!r} but its "
            "aws-admin capability has no region; set the capability region",
        )
    credentials = _capability_credentials(project)
    if credentials is None:
        raise ArtifactStorageError(
            "s3_configuration_invalid",
            f"project {project!r} declares artifacts bucket {bucket!r} but its "
            "aws-admin capability credentials are unavailable; configure "
            "access_key_id and secret_access_key",
        )
    upload_url = presign_s3_url(
        method="PUT",
        bucket=bucket,
        key=key,
        region=region,
        credentials=credentials,
        expires_s=ARTIFACT_PRESIGN_EXPIRES_S,
    )
    _upload_bytes(
        upload_url,
        bucket=bucket,
        key=key,
        content=checked,
        content_type=content_type,
    )
    return s3_handle(bucket, key, content_type)


def validate_s3_handle_owner(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    handle: dict[str, Any],
) -> None:
    """Refuse an S3 handle outside its configured project/tenant run prefix."""
    from yoke_core.domain.handlers.qa_artifact_presign import resolve_artifacts_bucket
    from yoke_core.domain.qa_artifact_handle import artifact_key_prefix
    from yoke_core.domain.qa_artifacts import case_artifact_subject
    from yoke_core.domain.qa_artifact_broker import ArtifactBrokerError

    owner = requirement_storage_owner(conn, requirement_id)
    try:
        configured = resolve_artifacts_bucket(
            conn, int(owner["project_id"]), owner["target_env"]
        )
    except ArtifactBrokerError as exc:
        raise ArtifactStorageError(exc.code, str(exc)) from exc
    except ValueError as exc:
        raise ArtifactStorageError("s3_configuration_invalid", str(exc)) from exc
    if configured is None:
        raise ArtifactStorageError(
            "s3_not_configured",
            f"project {owner['project']!r} has no configured artifact bucket",
        )
    _environment, bucket, storage_prefix = configured
    expected = artifact_key_prefix(
        str(owner["project"]),
        case_artifact_subject(owner),
        int(run_id),
        storage_prefix=storage_prefix,
    )
    if handle.get("bucket") != bucket or not str(handle.get("key", "")).startswith(
        expected
    ):
        raise ArtifactStorageError(
            "artifact_store_mismatch",
            "S3 artifact handle is outside the configured project/tenant "
            f"run prefix s3://{bucket}/{expected}",
        )


def store_artifact_file(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    path: str | Path,
    filename: str | None = None,
    content_type: Optional[str] = None,
    before_local_write: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Read one submitted file and durably store it through the shared owner."""

    source = Path(path).expanduser()
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ArtifactStorageError(
            "artifact_source_unavailable",
            f"artifact source {source} could not be read: {exc}",
        ) from exc
    return store_artifact_bytes(
        conn,
        requirement_id=requirement_id,
        run_id=run_id,
        filename=filename or source.name,
        content=content,
        content_type=content_type,
        before_local_write=before_local_write,
    )


__all__ = "ArtifactStorageError ARTIFACT_PRESIGN_EXPIRES_S MAX_ARTIFACT_BYTES requirement_storage_owner store_artifact_bytes store_artifact_file validate_s3_handle_owner".split()
