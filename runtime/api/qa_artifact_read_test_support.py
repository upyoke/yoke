"""Seed helpers for authorized QA artifact reads."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_qa_requirement,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.s3_presign import AwsCredentials


CREDS = AwsCredentials(
    access_key_id="AKIDEXAMPLE",
    secret_access_key="secret",
)
DEPLOYMENT_RUN_ID = "run-20260728-903"


def artifact_read_request(
    requirement_id: int,
    artifact_id: int,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.read",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload={"artifact_id": artifact_id},
    )


def seed_artifact(
    conn,
    *,
    handle: dict,
    metadata: dict | None = None,
) -> int:
    insert_item(conn, id=42, title="Evidence owner")
    insert_qa_requirement(
        conn,
        id=10,
        item_id=42,
        qa_kind="command",
        qa_phase="verification",
        blocking_mode="blocking",
    )
    run = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id, executor_type, qa_kind, verdict, created_at"
        ") VALUES (10, 'worktree_run', 'command', 'pass', "
        "'2026-07-26T12:00:00Z') RETURNING id",
    ).fetchone()
    artifact = conn.execute(
        "INSERT INTO qa_artifacts("
        "qa_run_id, artifact_type, content_type, artifact_handle, metadata, "
        "created_at"
        ") VALUES (%s, 'output', 'text/plain', %s, %s, "
        "'2026-07-26T12:00:00Z') RETURNING id",
        (
            run["id"],
            json.dumps(handle),
            json.dumps(metadata or {}),
        ),
    ).fetchone()
    conn.commit()
    return int(artifact["id"])


def seed_s3_configuration(conn, *, bucket: str) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sites ("
        "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,"
        "description TEXT, created_at TEXT NOT NULL, settings TEXT DEFAULT '{}')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS environments ("
        "id TEXT PRIMARY KEY, site TEXT NOT NULL, name TEXT NOT NULL,"
        "url TEXT, deploy_method TEXT, deploy_command TEXT,"
        "health_check_url TEXT, config_notes TEXT, last_deployed_at TEXT,"
        "created_at TEXT NOT NULL, settings TEXT DEFAULT '{}')"
    )
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES ('site-1', 1, 'core', '2026-07-28T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO environments (id, site, name, settings, created_at) "
        "VALUES ('env-prod', 'site-1', 'prod', %s, "
        "'2026-07-28T00:00:00Z')",
        (json.dumps({"artifacts": {"bucket": bucket}}),),
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, 'aws-admin', %s)",
        (json.dumps({"region": "us-east-1"}),),
    )
    conn.commit()


def seed_deployment_artifact(conn, *, handle: dict) -> int:
    insert_deployment_run(conn, id=DEPLOYMENT_RUN_ID)
    requirement = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=DEPLOYMENT_RUN_ID,
        qa_kind="plan_case",
        qa_phase="post_deploy",
    )
    run = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id, executor_type, qa_kind, verdict, created_at"
        ") VALUES (%s, 'worktree_run', 'command', 'pass', "
        "'2026-07-28T12:00:00Z') RETURNING id",
        (int(requirement["id"]),),
    ).fetchone()
    artifact = conn.execute(
        "INSERT INTO qa_artifacts("
        "qa_run_id, artifact_type, content_type, artifact_handle, metadata, "
        "created_at"
        ") VALUES (%s, 'output', 'text/plain', %s, '{}', "
        "'2026-07-28T12:00:00Z') RETURNING id",
        (int(run["id"]), json.dumps(handle)),
    ).fetchone()
    conn.commit()
    return int(artifact["id"])
