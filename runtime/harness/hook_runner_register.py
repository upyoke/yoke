"""Shared registration sequence for every session-registering hook path.

Owns ``_register_from_hook`` — the call sequence that resolves
executor / provider / model / entrypoint, derives the workspace, records
the session's process anchor, and calls ``register_session``. Three
callers drive the same sequence so they never drift apart on detection
precedence: the SessionStart canonical path, the UserPromptSubmit
safety-net path, and ``ensure_registered_from_hook`` — the
ensure-register-on-first-sight path the dispatch telemetry flush drives
when ANY hook event (PreToolUse/PostToolUse included) observes a session
id with no ``harness_sessions`` row. Tool-call hooks are the only
empirically guaranteed event class (a live desktop session ran full
PreToolUse chains all day with neither env stamp nor any
SessionStart/UserPromptSubmit delivery), so registration must not depend
on lifecycle events firing.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from runtime.harness.hook_runner.session_lifecycle_client import (
    register_harness_session,
)
from runtime.harness.hook_runner_register_identity import (
    placeholder_identity_can_upgrade,
)
from runtime.harness.hook_runner.target import (
    is_yoke_target,
    resolve_hook_script_dir,
    resolve_target_root,
)


def _register_from_hook(
    payload_json: str,
    session_id: str,
    *,
    transcript_path: str = "",
    record_anchor: bool = True,
    executor_hint: str = "",
    register_in_process: bool = False,
    actor_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> tuple[str, str, str, str, Optional[str]]:
    """Register the current session in harness_sessions.

    Called from two places with different signals:

    - SessionStart (``run_session_start_hook``): payload carries the
      authoritative ``model``, so we prefer it.
    - UserPromptSubmit (``run_user_prompt_submit_hook``): no model in
      payload; ``detect_model`` resolves via transcript/argv/env
      fallbacks. This path is idempotent safety-net — if SessionStart
      already registered the session, ``register_session`` hits
      ``SESSION_EXISTS`` and the sessions_lifecycle layer still
      upgrades a stored placeholder when the transcript finally
      reveals a real model ID.

    Returns ``(error_or_empty, executor, provider, model, entrypoint)``.
    ``error_or_empty`` is "" on success or a short error string on
    failure. Returns empty-executor tuple when the target isn't a
    Yoke repo.
    """
    root = ""
    if not register_in_process:
        # Client-checkout gating: answers "is this checkout a Yoke
        # target". Server-side (register_in_process) the answer is
        # trivially yes — the process IS the control plane.
        script_dir = resolve_hook_script_dir()
        root = resolve_target_root(script_dir)
        if not root:
            return ("", "", "", "", None)

        from runtime.harness.hook_helpers import resolve_yoke_db

        db_path = resolve_yoke_db(script_dir)
        if not is_yoke_target(root, db_path):
            return ("", "", "", "", None)

    from runtime.harness.hook_helpers import (
        _is_placeholder_model,
        detect_entrypoint,
        detect_executor,
        detect_model,
        detect_provider,
    )

    payload_model = ""
    payload_entrypoint = ""
    payload_lane = ""
    payload_project_id: Optional[int] = project_id
    effective_transcript_path = transcript_path
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            m = payload.get("model", "")
            if isinstance(m, str) and m and not _is_placeholder_model(m):
                payload_model = m
            ep = payload.get("entrypoint", "")
            if isinstance(ep, str):
                payload_entrypoint = ep
            lane = payload.get("execution_lane", "")
            if isinstance(lane, str):
                payload_lane = lane.strip()
            if payload_project_id is None:
                payload_project_id = _payload_project_id(payload.get("project_id"))
            if not effective_transcript_path:
                tp = payload.get("transcript_path", "")
                if isinstance(tp, str):
                    effective_transcript_path = tp

    executor = executor_hint or detect_executor()
    provider = detect_provider(executor)
    model = payload_model or detect_model(executor, transcript_path=effective_transcript_path)
    # Relayed payloads carry the CLIENT's entrypoint (merged from the wire);
    # local payloads never carry one, so local detection is unchanged.
    entrypoint = payload_entrypoint or detect_entrypoint()

    # Process-anchor registry write: hooks run as children of the
    # per-session harness agent process, so this is the one place the
    # session_id -> ancestor-pid binding can be recorded for shell-side
    # ambient identity resolution. Best-effort and independent of DB
    # registration success — anchor-based self-identification must work
    # even when the control plane is briefly unreachable. Remote (server)
    # evaluation passes record_anchor=False: the server's process tree is
    # not the caller's, so the hook relay writes the anchor client-side.
    if record_anchor:
        _record_process_anchor(session_id, effective_transcript_path)

    if register_in_process:
        # Server runtime: the checkout-layout subprocess wrapper cannot
        # exist in the installed-package container; call the idempotent
        # domain registrar directly (SESSION_EXISTS semantics included).
        # The verified bearer-token actor binds here — the relayed
        # mirror of the machine actor local registration resolves.
        payload_cwd = ""
        if payload_json:
            try:
                parsed = json.loads(payload_json)
                if isinstance(parsed, dict) and isinstance(parsed.get("cwd"), str):
                    payload_cwd = parsed["cwd"]
            except (json.JSONDecodeError, TypeError):
                pass
        err = _register_in_process(
            session_id, executor, provider, model, payload_cwd, entrypoint,
            actor_id=actor_id, execution_lane=payload_lane or None,
            project_id=payload_project_id,
        )
        return (err, executor, provider, model, entrypoint)

    # On https-default machines register_harness_session self-skips —
    # the relayed hook chain's server-side ensure-register owns the
    # session row there (see session_lifecycle_client).
    err = register_harness_session(
        root=root,
        session_id=session_id,
        executor=executor,
        provider=provider,
        model=model,
        entrypoint=entrypoint,
    )
    return (err, executor, provider, model, entrypoint)


def _register_in_process(
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    entrypoint: Optional[str],
    *,
    actor_id: Optional[int] = None,
    execution_lane: Optional[str] = None,
    project_id: Optional[int] = None,
) -> str:
    """Direct domain registration for server-side (remote) contexts.

    Project routing policy is server-side shared authority: when a project
    declares ``session-routing``, resolve the executor's lane from that DB
    capability. ``execution_lane`` is only a no-policy fallback for older
    source-dev/test paths.
    """
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.sessions_lifecycle_registry import register_session

        if project_id is None:
            return "session registration requires project_id"
        conn = db_helpers.connect()
        try:
            resolved_lane = execution_lane
            from yoke_core.api.routing_config import (
                load_project_routing_settings,
                load_routing_config,
                resolve_execution_lane,
            )

            project_routing = load_project_routing_settings(conn, project_id)
            if project_routing:
                routing = load_routing_config(
                    "/__yoke_no_local_routing_config__",
                    project_settings=project_routing,
                )
                resolved_lane = resolve_execution_lane(
                    executor=executor,
                    explicit_lane=execution_lane,
                    routing_config=routing,
                )
            lane_kwargs = {"execution_lane": resolved_lane} if resolved_lane else {}
            register_session(
                conn,
                session_id=session_id,
                executor=executor,
                provider=provider,
                model=model,
                workspace=workspace,
                entrypoint=entrypoint,
                actor_id=actor_id,
                project_id=project_id,
                **lane_kwargs,
            )
        finally:
            conn.close()
        return ""
    except Exception as exc:  # noqa: BLE001 — best-effort net, mirror the wrapper
        return str(exc)


def _record_process_anchor(session_id: str, transcript_path: str) -> None:
    """Best-effort anchor write; never raises into the hook path."""
    try:
        from yoke_core.domain.session_process_anchors import (
            record_session_anchor,
        )

        record_session_anchor(session_id, transcript_path=transcript_path)
    except Exception:  # noqa: BLE001 — anchor recording must never break hooks
        return


def _payload_project_id(value: Any) -> Optional[int]:
    try:
        project_id = int(value)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def ensure_registered_from_hook(
    conn: Any,
    payload_json: str,
    session_id: str,
    *,
    transcript_path: str = "",
    record_anchor: bool = True,
    executor_hint: str = "",
    register_in_process: bool = False,
    force_reregister: bool = False,
    actor_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> bool:
    """Idempotently register ``session_id`` when it has no session row.

    Called from the dispatch telemetry flush with the flush's already-open
    events connection, so the row-existence probe costs one indexed SELECT
    on a live connection — zero added round-trips when the session is
    registered (the common case). Only a *positive* no-row finding drives
    registration; a failed lookup registers nothing (a broken DB would
    fail the registration subprocess too).

    Tool-call payloads (PreToolUse/PostToolUse) lack the model/source
    fields SessionStart carries; ``_register_from_hook`` already tolerates
    that via the detect_* fallbacks (the UserPromptSubmit path exercises
    the same shape). Concurrent callers are race-safe — the underlying
    ``register_session`` treats an existing row as SESSION_EXISTS and
    upgrades placeholders in place.

    ``actor_id`` (server side) is the verified bearer-token actor bound
    to the registered row — relayed registration mirrors the machine
    actor that local registration resolves.

    Returns True when a registration attempt was driven.
    """
    if not session_id or session_id == "unknown" or conn is None:
        return False
    try:
        if not force_reregister:
            from yoke_core.domain.events_session_actor import session_actor_lookup

            found, stored_actor_id = session_actor_lookup(conn, session_id)
            # An existing row with no bound actor still needs the verified
            # token actor (the heartbeat backfill can register the relayed
            # session first, actor-less) — drive registration so the
            # SESSION_EXISTS actor backfill binds it.
            needs_actor_backfill = (
                found is True and stored_actor_id is None and actor_id is not None
            )
            # A registered row stuck on placeholder identity still needs a
            # drive when the wire payload carries the real value — the
            # registrar's SESSION_EXISTS branch upgrades in place.
            needs_identity_upgrade = (
                found is True
                and not needs_actor_backfill
                and placeholder_identity_can_upgrade(conn, payload_json, session_id)
            )
            if (
                found is not False
                and not needs_actor_backfill
                and not needs_identity_upgrade
            ):
                return False
        # force_reregister (registration-class remote events): the
        # registrar's SESSION_EXISTS path upgrades a stored placeholder
        # model from the wire-carried real one and never downgrades.
        _register_from_hook(
            payload_json, session_id, transcript_path=transcript_path,
            record_anchor=record_anchor, executor_hint=executor_hint,
            register_in_process=register_in_process, actor_id=actor_id,
            project_id=project_id,
        )
        return True
    except Exception:  # noqa: BLE001 — the safety net must never break dispatch
        return False
