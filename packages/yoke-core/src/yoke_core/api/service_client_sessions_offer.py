"""Session offer command handler — cmd_session_offer plus its private helpers.

Owns the CLI surface for ``service-client session-offer``: frontier construction
from the scheduler result, project resolution from the workspace, and the
parent-module monkeypatch lookup that lets tests patch the master service-client
module while subprocess invocations still resolve canonical bindings.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

import yoke_core.api.service_client_shared as _shared
from yoke_harness.hooks.identity import (
    _is_placeholder_model,
    detect_model,
    is_claude,
    is_codex,
)

from yoke_core.api.service_client_shared import (
    _get_config_path,
    _get_db_readwrite,
    _get_db_readonly,
    SessionError,
    SessionOffer,
    emit_next_action_chosen,
    emit_post_decision_telemetry,
    get_max_chain_steps,
    load_routing_config,
    release_item_claim_for_execution,
    resolve_execution_lane,
    session_offer_with_ownership,
    set_session_mode,
    should_emit_drift_review_checkpoint,
)
from yoke_core.api.routing_config import (
    PROJECT_ROUTING_CAPABILITY,
    load_process_offer_policy,
    load_project_routing_settings,
)
from yoke_core.domain.frontier_compute import _canonical_project_label
from yoke_core.domain.session_decision_process_gate import merge_skip_memory_with_policy, record_disabled_process_skip
from yoke_core.domain.session_project_scope import (
    parse_project_cli_arg,
    resolve_session_project_scope,
)
from yoke_core.api.service_client_sessions_offer_dispatch import dispatch_decision_engine
from yoke_core.api.service_client_sessions_offer_invariant import CLI_SURFACE, handle_charge_invariant
from yoke_core.api.service_client_sessions_frontier import (
    build_frontier_state_from_schedule as _build_frontier_state_from_schedule,
)


def _resolve_monkeypatchable(name: str):
    """Look up a function by name, preferring the parent service_client module.

    Tests monkeypatch attributes on ``yoke_core.api.service_client``.  When imported
    as a library, that module is in sys.modules, so the patched version is
    returned.  When running as a subprocess (``python3 -m ...``), the parent
    module is not in sys.modules under its package name, so we fall back to
    ``_shared`` which holds the original binding.
    """
    parent = sys.modules.get('yoke_core.api.service_client')
    if parent is not None:
        return getattr(parent, name)
    return getattr(_shared, name)


class SessionOfferCommandError(Exception):
    """User-facing failure from the shared session-offer runner."""


def run_session_offer(
    *,
    executor: str,
    provider: str,
    workspace: str,
    model: Optional[str] = None,
    lane: Optional[str] = None,
    session_id: Optional[str] = None,
    step: int = 1,
    supported_paths: Optional[List[str]] = None,
    project: Optional[str] = None,
) -> dict:
    """Run the canonical session-offer flow and return ``NextAction`` JSON."""
    if not session_id:
        if is_claude(executor) or is_codex(executor):
            raise SessionOfferCommandError(
                f"Error: session-offer for executor '{executor}' requires "
                f"--session-id (the canonical harness session ID). "
                f"Auto-generating a fallback ID is not allowed for supported harnesses. "
                f"Pass $CLAUDE_SESSION_ID (Claude Code) or $CODEX_THREAD_ID (Codex)."
            )
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        session_id = f"{executor}-{ts}"

    supported_paths = list(supported_paths or [])

    _config_path = _get_config_path()
    max_chain_steps = get_max_chain_steps(_config_path)

    conn = _get_db_readwrite()
    try:
        override = parse_project_cli_arg(project)
        try:
            project_scope = resolve_session_project_scope(conn, override=override)
        except ValueError as exc:
            raise SessionOfferCommandError(f"Error: {exc}") from exc
        project_label = _canonical_project_label(conn, project_scope)

        session_project_id: Optional[int] = None
        stored_model: Optional[str] = None
        try:
            session_row = conn.execute(
                "SELECT model, project_id FROM harness_sessions WHERE session_id=%s",
                (session_id,),
            ).fetchone()
        except Exception:
            session_row = None
        if session_row is not None:
            try:
                stored_model = session_row["model"]
                raw_project_id = session_row["project_id"]
            except (KeyError, TypeError):
                stored_model = session_row[0]
                raw_project_id = session_row[1] if len(session_row) > 1 else None
            try:
                session_project_id = (
                    int(raw_project_id) if raw_project_id is not None else None
                )
            except (TypeError, ValueError):
                session_project_id = None

        policy_project_id = session_project_id
        if policy_project_id is None and project_scope and len(project_scope) == 1:
            policy_project_id = int(project_scope[0])
        project_routing_settings = load_project_routing_settings(
            conn, policy_project_id,
        )
        routing_config = load_routing_config(
            _config_path,
            project_settings=project_routing_settings,
        )
        # caller --lane is advisory; ownership anchors on the row.
        resolved_lane = resolve_execution_lane(
            executor=executor,
            explicit_lane=None,
            routing_config=routing_config,
        )

        if not model:
            model = (
                stored_model
                if isinstance(stored_model, str)
                and not _is_placeholder_model(stored_model)
                else detect_model(executor)
            )

        offer = SessionOffer(
            session_id=session_id,
            executor=executor,
            provider=provider,
            model=model,
            workspace=workspace,
            execution_lane=resolved_lane,
            step=step,
            supported_paths=supported_paths,
        )

        # Per-project offer stance is DB-backed through session-routing.
        from yoke_core.domain.project_settings import get_project_int_for_id

        process_offer_policy = load_process_offer_policy(
            _config_path,
            project_settings=project_routing_settings,
            shared_project_source=(
                f"project {policy_project_id} capability {PROJECT_ROUTING_CAPABILITY}"
                if project_routing_settings and policy_project_id is not None
                else None
            ),
        )
        wip_cap = get_project_int_for_id(policy_project_id, "wip_cap")

        try:
            ownership = session_offer_with_ownership(
                conn,
                session_id=session_id,
                executor=executor,
                provider=provider,
                model=model,
                workspace=workspace,
                execution_lane=resolved_lane,
                caller_supplied_lane=lane,
                supported_paths=supported_paths,
                lane_allowed_paths=routing_config.lane_allowed_paths,
                step=step,
                project_scope=project_scope,
                wip_cap=wip_cap,
                max_chain_steps=max_chain_steps,
            )
        except SessionError as exc:
            if exc.code in ("NO_SESSION", "SESSION_ENDED"):
                raise SessionOfferCommandError(f"Error: {exc.message}") from exc
            raise
        authoritative_lane = ownership.get("authoritative_lane") or resolved_lane
        offer = offer.model_copy(update={
            "supported_paths": ownership.get("supported_paths") or [],
            "execution_lane": authoritative_lane,
        })
        effective_policy = merge_skip_memory_with_policy(process_offer_policy, ownership.get("chain_skip_memory"))

        result, drift_dict = dispatch_decision_engine(
            conn,
            offer=offer,
            ownership=ownership,
            project_scope=project_scope,
            routing_config=routing_config,
            effective_policy=effective_policy,
            session_id=session_id,
            step=step,
            resolve_monkeypatchable=_resolve_monkeypatchable,
        )

        # Reconcile eager offer-time claim when decision is not charge.
        _new_claim = ownership.get("new_claim")
        if _new_claim and result.action.value != "charge":
            _override_item = _new_claim.get("item_id")
            if _override_item:
                _release_result = release_item_claim_for_execution(
                    conn,
                    session_id,
                    str(_override_item),
                    "offer-override",
                )
                if not _release_result.get("released"):
                    raise SessionOfferCommandError(
                        f"Error: failed to release offer-time claim on "
                        f"{_override_item} before non-charge action "
                        f"'{result.action.value}': {_release_result}"
                    )

        _ok, _err = handle_charge_invariant(conn, session_id=session_id, result=result, new_claim=_new_claim, ownership=ownership, surface=CLI_SURFACE, project=project_label)
        if not _ok:
            raise SessionOfferCommandError(f"Error: {_err}")

        set_session_mode(conn, session_id, result.action.value)

        record_disabled_process_skip(
            conn,
            session_id=session_id,
            chain_step=step,
            project=project_label,
            action=result,
        )

        if should_emit_drift_review_checkpoint(result, drift_dict):
            # State first: advance each scoped project's checkpoint anchor,
            # then emit the matching telemetry event.
            from yoke_core.domain.strategy_checkpoints import (
                record_checkpoints,
            )
            record_checkpoints(
                conn, projects=project_scope, kind="drift_review",
            )
            conn.commit()
            _resolve_monkeypatchable('emit_drift_review_completed')(
                session_id=session_id,
                project=project_label,
                project_scope=project_scope,
                classification=drift_dict["classification"],
                summary=drift_dict["summary"],
                checkpoint_start=drift_dict["checkpoint_start"],
                reviewed_through=drift_dict["reviewed_through"],
                delivered_items=drift_dict.get("delivered_items"),
            )

        emit_next_action_chosen(
            session_id=session_id,
            action=result.action.value,
            reason=result.reason,
            correlation_id=result.correlation_id,
            project=project_label,
            chainable=result.chainable,
            step=step,
            supported_paths=ownership.get("supported_paths"),
            context=result.context,
        )

        emit_post_decision_telemetry(
            conn,
            session_id,
            action=result.action.value,
            reason=result.reason,
            actual_lane=authoritative_lane,
            context=result.context,
            project=project_label,
        )

        return result.model_dump()
    finally:
        conn.close()


def cmd_session_offer(args: List[str]) -> int:
    """Compute frontier state and decide the next action for a session offer.

    ``--model`` is optional; falls back to ``harness_sessions.model`` lookup
    then ``hook_helpers_model.detect_model``.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-offer", add_help=False)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--lane", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--supported-paths", default=None, help="Comma-separated canonical downstream paths.")
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Comma-separated project ids to narrow the frontier scope "
            "(e.g. 'yoke,example-project'). Default: all registered projects."
        ),
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-offer --executor E --provider P --workspace W [--model M] [--lane L] [--session-id S] [--step N] [--supported-paths P] [--project IDS]", file=sys.stderr)
        return 2

    supported_paths: List[str] = [
        p.strip()
        for p in (parsed.supported_paths or "").split(",")
        if p.strip()
    ]
    try:
        result = run_session_offer(
            executor=parsed.executor,
            provider=parsed.provider,
            model=parsed.model,
            workspace=parsed.workspace,
            lane=parsed.lane,
            session_id=parsed.session_id,
            step=parsed.step,
            supported_paths=supported_paths,
            project=parsed.project,
        )
        print(json.dumps(result))
        return 0
    except SessionOfferCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1


__all__ = [
    "SessionOfferCommandError",
    "_resolve_monkeypatchable",
    "_build_frontier_state_from_schedule",
    "run_session_offer",
    "cmd_session_offer",
]
