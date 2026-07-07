"""Client-side ``--wait`` loop for ``yoke github-actions check-ci``.

Sibling of :mod:`yoke_cli.commands.adapters.github_actions`. The wait
loop runs HERE, never in the server handler — a server-side loop blocks
one ``POST /v1/functions/call`` for the whole CI wait and exceeds the
https relay's read timeout. Each poll is an independent single-shot
``github_actions.check_ci`` dispatch over the active transport, so
waiting behaves identically in-process and against a deployed relay.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import TargetRef

# Module-level aliases so tests monkeypatch the wait loop's clock without
# rebinding ``time.*`` globally (same idiom as gh_rest_transport).
now = time.time
sleep = time.sleep


def wait_for_ci_completion(
    payload: Dict[str, Any],
    *,
    session_id: Optional[str],
    json_mode: bool,
    timeout_sec: int,
) -> int:
    """Poll the single-shot check until the run completes or budget ends.

    Budget exhaustion rewrites the last running response's state to
    ``timeout`` (the module form's semantics) while preserving the
    last-seen run info; failures and terminal states emit as-is.
    """
    ensure_handlers_loaded()
    actor = build_actor(session_id=session_id)
    start = now()
    appearance_budget = min(_appearance_timeout_seconds(), timeout_sec)
    while True:
        response = call_dispatcher(
            function_id="github_actions.check_ci",
            target=TargetRef(kind="global"),
            payload=dict(payload),
            actor=actor,
        )
        result = response.result or {}
        state = str(result.get("state") or "")
        if not response.success:
            return emit_response(response, json_mode=json_mode)

        # A just-pushed branch can report ``no_runs`` for a few seconds while
        # GitHub registers the triggered run. Keep polling for the run to
        # APPEAR within a bounded window rather than accepting ``no_runs``
        # immediately — otherwise the gate fails open, skipping CI it should
        # have waited for. After the window, ``no_runs`` is genuine.
        if state == "no_runs":
            if int(now() - start) < appearance_budget:
                print(
                    "  CI status: no run registered yet, waiting up to "
                    f"{appearance_budget}s for the run to appear...",
                    file=sys.stderr,
                )
                sleep(_poll_interval_seconds())
                continue
            return emit_response(response, json_mode=json_mode)

        if state != "running":
            return emit_response(response, json_mode=json_mode)

        elapsed = int(now() - start)
        if elapsed >= timeout_sec:
            timed_out = response.model_copy(
                update={"result": {**result, "state": "timeout"}},
            )
            return emit_response(timed_out, json_mode=json_mode)

        print(
            f"  CI status: {result.get('status') or 'running'} "
            f"(elapsed: {elapsed}s, timeout: {timeout_sec}s)",
            file=sys.stderr,
        )
        sleep(_poll_interval_seconds())


def _appearance_timeout_seconds() -> int:
    import importlib

    module = importlib.import_module("yoke_core.domain.github_actions_run_monitoring")
    return int(module.CHECK_CI_APPEARANCE_TIMEOUT_SEC)


def _poll_interval_seconds() -> int:
    import importlib

    module = importlib.import_module("yoke_core.domain.github_actions_run_monitoring")
    return int(module.CHECK_CI_POLL_INTERVAL_SEC)


__all__ = ["wait_for_ci_completion"]
