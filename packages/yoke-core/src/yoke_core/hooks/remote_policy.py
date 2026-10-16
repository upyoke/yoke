"""Remote-evaluation controls for the relay-split hook chain.

``POST /v1/hooks/evaluate`` serves the same policy chains as the in-process
runner, but the server cannot see the CLIENT machine. Each chain policy's
home is declared once in :mod:`yoke_contracts.hook_runner.policy_home`, which
the relay client reads too:

- ``CLIENT`` policies are evaluated by the relay client before it posts.
  Server-side evaluation skips each one with its module id recorded in the
  response's ``degraded`` list (the marker means "delegated to the client",
  not "protection off").
- ``SERVER`` policies run here as-is from the payload and the DB.
- ``SERVER_WITH_CLIENT_FACTS`` policies run here and read only the named
  client facts the relay client shipped in ``payload_extra``.

``RunControls`` is the runner-facing knob bundle: an injected total budget
(the remaining shared deadline), the skip classifier, payload augmentation,
the verified-token ``actor_id`` (server side), the ``flush_tail`` switch
(``False`` skips the telemetry/ensure-register tail), and result
write-backs (degraded markers, timeout flag, final outcome) callers need
but the ``(stdout, exit_code)`` return shape cannot carry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_contracts.hook_runner.policy_home import CLIENT_POLICIES
from yoke_contracts.hook_runner.project_scope import HookProjectScope

__all__ = [
    "DEADLINE_EXHAUSTED_MARKER",
    "RunControls",
    "remote_skip_marker",
]


# Appended to ``degraded`` when the propagated deadline expired before the
# chain finished. A deny computed before expiry is still rendered.
DEADLINE_EXHAUSTED_MARKER = "deadline_exhausted"


def remote_skip_marker(module_id: str) -> Optional[str]:
    """Server side of the split: skip client-home policies (the client ran them)."""
    if module_id in CLIENT_POLICIES:
        return module_id
    return None


@dataclass
class RunControls:
    """Cross-boundary knobs for ``run_event`` (relay-split evaluation).

    ``budget_ms`` overrides the config-resolved total deadline with the
    caller's remaining shared budget. ``skip_module`` maps a module id
    to a degraded marker (skip) or ``None`` (run). ``payload_extra`` merges
    into the parsed payload before context build (e.g. the request's
    ``agent_type``). ``actor_id`` is the server-verified bearer-token actor
    bound at ensure-register. ``project_scope`` is the in-process caller's
    already-resolved project membership (a remote run uses
    ``authorized_project_id`` instead). ``flush_tail=False`` skips the
    telemetry/ensure-register tail. ``degraded`` / ``timed_out`` /
    ``final_outcome`` are write-backs populated during the run, as is a
    remote run's ``deferred_telemetry``: the flush its caller runs after
    responding, given the server's request wall time in milliseconds.
    """

    budget_ms: Optional[int] = None
    skip_module: Optional[Callable[[str], Optional[str]]] = None
    payload_extra: dict[str, Any] = field(default_factory=dict)
    remote: bool = False
    actor_id: Optional[int] = None
    authorized_project_id: Optional[int] = None
    project_scope: Optional[HookProjectScope] = None
    flush_tail: bool = True
    degraded: list[str] = field(default_factory=list)
    denial_audit: dict[str, str] = field(default_factory=dict)
    timed_out: bool = False
    final_outcome: str = ""
    deferred_telemetry: Optional[Callable[[int], None]] = None
