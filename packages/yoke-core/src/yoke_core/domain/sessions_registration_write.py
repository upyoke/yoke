"""Persist new session scope and refresh mutable facts on reactivation."""

from typing import Any

from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain.session_model_columns import MODEL_COLUMNS, facts_values
from yoke_core.domain.session_scope_identity import SessionScope


def insert_registration(
    conn: Any,
    *,
    placeholder: str,
    session_id: str,
    executor: str,
    surface: str | None,
    executor_version: str | None,
    machine_id: str | None,
    provider: str,
    model_facts: SessionModelFacts,
    execution_level: str,
    workspace: str,
    mode: str,
    now: Any,
    envelope_json: str | None,
    actor_id: int,
    scope: SessionScope,
    native_thread_id: str | None,
    has_native_thread: bool,
    has_episode: bool,
) -> None:
    """Write the exclusive scope only when the session is first created."""
    columns = (
        "session_id, executor, executor_surface, executor_version, machine_id, "
        "provider, " + ", ".join(MODEL_COLUMNS) + ", execution_level, workspace, "
        "mode, offered_at, last_heartbeat, ended_at, offer_envelope, actor_id, "
        "project_id, org_id"
    )
    values = [
        session_id,
        executor,
        surface,
        executor_version,
        machine_id,
        provider,
        *facts_values(model_facts),
        execution_level,
        workspace,
        mode,
        now,
        now,
        None,
        envelope_json,
        actor_id,
        scope.project_id,
        scope.org_id,
    ]
    if has_native_thread:
        columns += ", native_thread_id"
        values.append(native_thread_id)
    if has_episode:
        columns += ", episode_started_at"
        values.append(now)
    placeholders = ", ".join([placeholder] * len(values))
    conn.execute(
        f"INSERT INTO harness_sessions ({columns}) VALUES ({placeholders})",
        tuple(values),
    )


def reactivate_registration(
    conn: Any,
    *,
    placeholder: str,
    session_id: str,
    provider: str,
    model_facts: SessionModelFacts,
    execution_level: str,
    workspace: str,
    mode: str,
    envelope_json: str | None,
    executor_version: str | None,
    machine_id: str | None,
    native_thread_id: str | None,
    now: Any,
    actor_id: int,
    replace_actor: bool,
    has_native_thread: bool,
    has_episode: bool,
) -> Any:
    """Refresh an ended session without assigning either scope column."""
    p = placeholder
    actor_clause = (
        f", actor_id = {p}"
        if replace_actor
        else f", actor_id = COALESCE(actor_id, {p})"
    )
    episode_clause = f", episode_started_at = {p}" if has_episode else ""
    thread_clause = (
        f", native_thread_id = COALESCE({p}, native_thread_id)"
        if has_native_thread
        else ""
    )
    model_assignments = ", ".join(f"{column} = {p}" for column in MODEL_COLUMNS)
    values = [
        provider,
        *facts_values(model_facts),
        execution_level,
        workspace,
        mode,
        envelope_json,
        executor_version,
        machine_id,
    ]
    if has_native_thread:
        values.append(native_thread_id)
    if has_episode:
        values.append(now)
    values.extend((actor_id, session_id))
    return conn.execute(
        f"""UPDATE harness_sessions
           SET provider = {p}, {model_assignments}, execution_level = {p},
               workspace = {p}, mode = {p}, ended_at = NULL,
               offer_envelope = {p}, executor_version = {p}, machine_id = {p}
               {thread_clause}{episode_clause}{actor_clause}
           WHERE session_id = {p} AND ended_at IS NOT NULL""",
        tuple(values),
    )
