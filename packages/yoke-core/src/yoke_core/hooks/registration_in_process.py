"""Direct domain registration for contexts that hold the control plane.

The server runtime and a local-authority machine both register through the
domain registrar in-process: the checkout-layout subprocess wrapper cannot
exist inside the installed-package container, and a machine that owns its
database has nothing to relay to. Split out of
:mod:`yoke_core.hooks.registration`, which owns the detection sequence that
decides WHICH registration path runs; this module owns only the call itself.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.hooks.registration_identity import project_lane_for_executor


def _register_in_process(
    session_id: str,
    executor: str,
    provider: str,
    model_facts: SessionModelFacts,
    workspace: str,
    entrypoint: Optional[str],
    *,
    actor_id: Optional[int] = None,
    execution_lane: Optional[str] = None,
    project_id: Optional[int] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    native_thread_id: Optional[str] = None,
    driver: Optional[dict] = None,
) -> str:
    """Direct domain registration for server-side (remote) contexts.

    ``driver`` is the dispatch tail's driving-process block (pid, ppid, and
    the hook event that ran). It is what a reactivation stamps on its own
    ``HarnessSessionStarted`` context, so a revived session names the process
    that revived it whether or not a wake attempt was in flight.

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
            resolved_lane = (
                project_lane_for_executor(
                    conn,
                    project_id,
                    executor,
                    explicit_lane=execution_lane,
                )
                or execution_lane
            )
            lane_kwargs = {"execution_lane": resolved_lane} if resolved_lane else {}
            register_session(
                conn,
                session_id=session_id,
                executor=executor,
                provider=provider,
                model_facts=model_facts,
                workspace=workspace,
                entrypoint=entrypoint,
                actor_id=actor_id,
                project_id=project_id,
                executor_version=executor_version,
                machine_id=machine_id,
                native_thread_id=native_thread_id,
                driver=driver,
                **lane_kwargs,
            )
        finally:
            conn.close()
        return ""
    except Exception as exc:  # noqa: BLE001 — best-effort net, mirror the wrapper
        return str(exc)


__all__ = ["_register_in_process"]
