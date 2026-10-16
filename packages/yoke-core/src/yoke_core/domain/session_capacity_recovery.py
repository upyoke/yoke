"""Recover a capacity-stopped worker through ordinary same-level placement."""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any, Mapping

from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_contracts.model_reference import lookup_model_reference
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    is_placeholder_model,
)
from yoke_contracts.session_control.native_model_parsers import (
    cursor_selector_without_effort,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.project_identity import placeholder, render_item_ref
from yoke_core.domain.session_launch_store import get_launch_by_dedupe, value
from yoke_core.domain.session_launch_types import (
    DEFAULT_LAUNCH_DEADLINE_SECONDS,
    SessionLaunchError,
)
from yoke_core.domain.session_recovery_facts import resume_episode_key
from yoke_core.domain.session_scope_identity import session_scope_of
from yoke_core.domain.work_claim_target_sql import scope_int_sql


def capacity_catalog(conn: Any, *, now: Any):
    from yoke_core.domain.model_reference_store import revision_at

    try:
        return revision_at(conn, now)["records"]
    except ModelReferenceError as exc:
        raise SessionLaunchError(
            "capacity_recovery_catalog_unavailable",
            (
                f"Effective model catalog is unavailable ({exc.code}: {exc}). "
                "Recovery: ask the model-catalog operator to publish a valid revision "
                "covering this time, then retry capacity recovery."
            ),
        ) from exc


def capacity_model_key(surface: str, model: str | None, *, records) -> str:
    """Exclude the same model on every surface, including native variants."""
    token = str(model or "").strip().lower()
    if surface == "cursor-cli":
        token = cursor_selector_without_effort(token).removeprefix("cursor-")
    token = (
        token.removesuffix("-fast")
        .removesuffix("-thinking")
        .removesuffix(CLAUDE_CONTEXT_TIER_SUFFIX)
    )
    lookup = lookup_model_reference(token, records)
    return lookup.record.model_id if lookup.record is not None else token


def recovery_key(state: Mapping[str, Any]) -> str:
    return f"capacity-successor:{state['session_id']}:{state['episode_key']}"


def capacity_recovery_state(conn: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Read a committed launch even if the poll died before recording its receipt."""
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT state,launch_id,result_code FROM session_launches WHERE idempotency_key={p} "
        f"AND requester_actor_id={p}",
        (recovery_key(state), state["actor_id"]),
    ).fetchone()
    if row is not None:
        launch_state = str(value(row, "state", 0))
        launch_id = str(value(row, "launch_id", 1))
        if launch_state in {"failed", "expired", "cancelled"}:
            return {
                **state,
                "status": "capacity_recovery_refused",
                "reason": (
                    f"capacity_successor_failed: launch {launch_id} {launch_state} "
                    f"({value(row, 'result_code', 2)}). Recovery: inspect and reconcile "
                    f"`yoke session-control launch get {launch_id} --json` before restaffing."
                ),
            }
        return {
            **state,
            "status": "capacity_recovery_pending",
            "reason": (
                f"successor launch {launch_id} is {launch_state}; predecessor retains custody until registration"
            ),
        }
    return state


def _record_refusal(
    conn: Any, state: Mapping[str, Any], exc: SessionLaunchError
) -> None:
    """The session observation owns diagnosed recovery refusal, not telemetry."""
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT native_turn_end_observation,last_tool_call_at FROM harness_sessions WHERE session_id={p}"
        + (" FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""),
        (state["session_id"],),
    ).fetchone()
    if row is None or resume_episode_key(row[1]) != state["episode_key"]:
        conn.rollback()
        return
    observation = json_helper.loads_text(row[0] or "{}")
    observation["capacity_recovery_refusal"] = {
        "code": exc.code,
        "detail": str(exc),
        "episode_key": state["episode_key"],
    }
    conn.execute(
        f"UPDATE harness_sessions SET native_turn_end_observation={p} WHERE session_id={p}",
        (json_helper.dumps_compact(observation), state["session_id"]),
    )
    conn.commit()


def _excluded_models(
    conn: Any, state: Mapping[str, Any], *, now: Any
) -> tuple[str, ...]:
    excluded = []
    if state["episode_key"] == resume_episode_key(None):
        p = placeholder(conn)
        row = conn.execute(
            "SELECT level_placement FROM session_launches "
            f"WHERE registered_session_id={p} OR native_session_id={p} "
            "ORDER BY created_at DESC LIMIT 1",
            (state["session_id"], state["session_id"]),
        ).fetchone()
        if row:
            prior = json_helper.loads_text(row[0] or "{}")
            excluded.extend(
                (prior.get("capacity_recovery") or {}).get("excluded_models") or []
            )
    excluded.append(
        capacity_model_key(
            str(state["executor_surface"]),
            state["model"],
            records=capacity_catalog(conn, now=now),
        )
    )
    return tuple(dict.fromkeys(excluded))


def relaunch_capacity_worker(
    conn: Any, *, state: Mapping[str, Any], now: Any
) -> dict[str, Any]:
    """Create once, retaining the claim and all lane/checkpoint bytes on refusal."""
    from yoke_core.domain.session_launch_authorization import launch_authorization
    from yoke_core.domain.session_launch_mandate import launch_request_for_create
    from yoke_core.domain.session_launch_requests import create_launch

    p = placeholder(conn)
    claim_item_id = scope_int_sql(conn, "scope", "item_id")
    try:
        scope = session_scope_of(state)
        if scope.project_id is None:
            raise SessionLaunchError(
                "capacity_recovery_project_required",
                "Item capacity recovery requires a project session. Recovery: "
                "open a session in the project folder.",
            )
        claims = conn.execute(
            f"SELECT id,target_kind,{claim_item_id} AS item_id FROM work_claims "
            f"WHERE session_id={p} AND released_at IS NULL ORDER BY id",
            (state["session_id"],),
        ).fetchall()
        if len(claims) != 1 or claims[0][1] != "item":
            raise SessionLaunchError(
                "capacity_recovery_claim_scope",
                (
                    "Automatic capacity recovery requires exactly one item claim. "
                    "Recovery: steering must checkpoint and restaff the session's holdings."
                ),
            )
        if (
            not state.get("execution_level")
            or is_placeholder_model(state.get("model"))
            or not state.get("actor_id")
            or not state.get("machine_id")
        ):
            raise SessionLaunchError(
                "capacity_recovery_identity_missing",
                (
                    "Worker model, actor, level or machine is unresolved. Recovery: steering must "
                    "correct the session identity before restaffing at its required level."
                ),
            )
        ref = render_item_ref(conn, int(claims[0][2]), required=True)
        auth = launch_authorization(
            conn,
            actor_id=int(state["actor_id"]),
            project_id=scope.project_id,
            session_id=None,
        )
        existing = get_launch_by_dedupe(conn, auth.actor_id, recovery_key(state))
        if existing is not None:
            return {"session_id": state["session_id"], "launch_id": existing.launch_id}
        parsed = LaunchCreateRequest(
            project=str(scope.project_id),
            item=ref,
            compose_mandate=True,
            idempotency_key=recovery_key(state),
            instructions=(
                f"Capacity recovery from session {state['session_id']}: provider refused "
                f"model {state['model']} with {state['error_message']!r}; "
                f"{state['attempts']} same-option retries spent. The same claim transfers "
                "at registration. Reuse the registered lane, preserve dirty files and "
                "read the existing Progress Log, git status and git log before continuing."
            ),
        )
        request = launch_request_for_create(
            conn,
            parsed,
            project_id=scope.project_id,
            deadline_seconds=DEFAULT_LAUNCH_DEADLINE_SECONDS,
            actor_id=auth.actor_id,
        )
        request = replace(
            request,
            level=str(state["execution_level"]),
            machine_id=str(state["machine_id"]),
            excluded_models=_excluded_models(conn, state, now=now),
            capacity_predecessor_session_id=str(state["session_id"]),
        )
        outcome = create_launch(conn, auth=auth, request=request, now=now)
        return {
            "session_id": state["session_id"],
            "launch_id": outcome.launch.launch_id,
        }
    except Exception as failure:
        conn.rollback()
        if isinstance(failure, SessionLaunchError):
            exc = failure
        else:
            logging.getLogger(__name__).exception(
                "capacity_recovery_failed for %s", state["session_id"]
            )
            exc = SessionLaunchError(
                "capacity_recovery_failed",
                (
                    f"Capacity recovery failed unexpectedly ({type(failure).__name__}); custody is retained. "
                    "Recovery: steering must inspect server diagnostics and correct the failure before restaffing."
                ),
            )
        _record_refusal(conn, state, exc)
        return {
            "session_id": state["session_id"],
            "status": "capacity_recovery_refused",
            "code": exc.code,
            "detail": str(exc),
        }
