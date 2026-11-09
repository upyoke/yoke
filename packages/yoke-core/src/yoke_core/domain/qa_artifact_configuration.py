"""Artifact storage environment and capability resolution."""

from __future__ import annotations
import json
from typing import Dict, List, Optional, Tuple
from yoke_core.domain.qa_handler_outcomes import _p


def resolve_artifacts_bucket(
    conn,
    project_id: int,
    target_env: Optional[str],
) -> Optional[Tuple[str, str, Optional[str]]]:
    """Return ``(env_name, bucket, storage_prefix)`` or ``None``.

    Reads ``environments.settings.artifacts.bucket`` directly on the
    handler's connection (single three-column read; the full renderer
    settings loader opens its own connection and resolves capabilities
    this path does not need).
    """
    from yoke_core.domain.qa_artifact_broker import broker_config
    from yoke_core.domain.schema_common import _table_exists

    broker = broker_config()
    if broker is not None:
        return str(target_env or "hosted"), broker.bucket, broker.prefix
    if not _table_exists(conn, "sites") or not _table_exists(conn, "environments"):
        return None
    p = _p(conn)
    rows = conn.execute(
        "SELECT e.name, e.settings FROM environments e "
        "JOIN sites s ON s.id = e.site "
        f"WHERE s.project_id = {p}",
        (int(project_id),),
    ).fetchall()
    buckets: Dict[str, tuple[str, Optional[str]]] = {}
    for row in rows:
        name, raw = str(row[0]), row[1]
        try:
            settings = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        artifacts = settings.get("artifacts")
        bucket = artifacts.get("bucket") if isinstance(artifacts, dict) else None
        if isinstance(bucket, str) and bucket.strip():
            raw_prefix = artifacts.get("prefix")
            if raw_prefix in (None, ""):
                prefix = None
            elif isinstance(raw_prefix, str):
                from yoke_core.domain.qa_artifact_handle import safe_storage_prefix

                prefix = safe_storage_prefix(raw_prefix)
            else:
                raise ValueError(
                    f"environment {name!r} artifacts.prefix must be a string"
                )
            buckets[name] = (bucket.strip(), prefix)
    if not buckets:
        return None
    order: List[str] = []
    if target_env:
        order.append(str(target_env))
    order.append("prod")
    order.extend(sorted(buckets))
    for name in order:
        if name in buckets:
            bucket, prefix = buckets[name]
            return name, bucket, prefix
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
        settings = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    except (TypeError, ValueError):
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
