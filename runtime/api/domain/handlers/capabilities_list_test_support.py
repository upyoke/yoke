"""Shared builders for capability-list handler tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def iso_timestamp(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def capabilities_list_request(
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.capabilities.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def insert_capability(
    conn,
    cap_type: str,
    *,
    project_id: int = 1,
    settings: str = "{}",
    verified_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO project_capabilities ("
        "project_id, type, settings, verified_at, created_at"
        ") VALUES (%s, %s, %s, %s, %s)",
        (project_id, cap_type, settings, verified_at, iso_timestamp()),
    )
    conn.commit()


def insert_github_binding(
    conn,
    *,
    project_id: int = 1,
    installation_id: str = "inst-1",
    binding_verified_at: str | None = None,
    installation_verified_at: str | None = None,
    installation_status: str = "active",
) -> None:
    now = iso_timestamp()
    conn.execute(
        "INSERT INTO github_app_installations ("
        "installation_id, account_id, account_login, account_type, "
        "status, last_verified_at, created_at, updated_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (installation_id) DO NOTHING",
        (
            installation_id,
            "acct-1",
            "example-org",
            "Organization",
            installation_status,
            installation_verified_at,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO project_github_repo_bindings ("
        "project_id, installation_id, repository_id, github_repo, "
        "last_verified_at, created_at, updated_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            project_id,
            installation_id,
            f"repo-{project_id}",
            "example-org/example-repo",
            binding_verified_at,
            now,
            now,
        ),
    )
    conn.commit()
