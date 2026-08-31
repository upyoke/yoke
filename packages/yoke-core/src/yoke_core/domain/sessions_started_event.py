"""What ``HarnessSessionStarted`` reports about a registered session.

Assembled after the row is written rather than from the caller's inputs,
because reactivation can resolve a different answer than it was handed:
executor and surface are write-once across an episode boundary, and the
model facts are the merge of the reading with what the row already proved.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.session_model_facts import SessionModelFacts


def session_started_context(
    conn: Any,
    *,
    placeholder: str,
    session_id: str,
    fallback_executor: str,
    fallback_surface: Optional[str],
    provider: str,
    model_facts: SessionModelFacts,
    execution_lane: str,
    workspace: str,
    mode: str,
    executor_version: Optional[str],
    machine_id: Optional[str],
    project_id: int,
    entrypoint: Optional[str],
    reactivation_driver: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the started-event context from the row as it now stands."""
    stored = conn.execute(
        "SELECT executor, executor_surface FROM harness_sessions "
        f"WHERE session_id = {placeholder}",
        (session_id,),
    ).fetchone()
    context: Dict[str, Any] = {
        "executor": stored["executor"] if stored is not None else fallback_executor,
        "provider": provider,
        "model": model_facts.model,
        "requested_model": model_facts.requested_model,
        "execution_lane": execution_lane,
        "workspace": workspace,
        "mode": mode,
    }
    surface = stored["executor_surface"] if stored is not None else fallback_surface
    if surface:
        context["executor_surface"] = surface
    if executor_version:
        context["executor_version"] = executor_version
    if machine_id:
        context["machine_id"] = machine_id
    context["project_id"] = project_id
    if entrypoint:
        context["entrypoint"] = entrypoint
    context.update(reactivation_driver)
    return context


__all__ = ["session_started_context"]
