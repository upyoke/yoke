"""Fail-open rendering for a hook relay that could not reach the server.

Transport failure must never block the tool call the hook was guarding, so
the relay degrades to a local-only allow that carries the shared degraded
warning on each harness's own surface (`yoke_contracts.hook_runner.degraded`).
"""

from __future__ import annotations

import sys

from yoke_contracts.hook_runner.degraded import infrastructure_reply

from yoke_harness.hooks.identity import detect_executor
from yoke_harness.hooks.relay_identity_guard import print_execution_provenance


DEGRADED_MARKER = "YOKE_HOOK_DEGRADED"


def degrade_to_noop(
    event_name: str,
    detail: str,
    *,
    preserved_stdout: str = "",
) -> int:
    """Fail open for hook transport/local harness failures."""
    # A terminal event never carries a continuation out of a failed relay.
    preserved = "" if event_name in {"Stop", "SessionEnd"} else preserved_stdout
    stdout = infrastructure_reply(
        event_name,
        detect_executor(),
        f"{DEGRADED_MARKER}: hook relay unreachable, server guards skipped ({detail})",
        preserved,
    )
    print_execution_provenance(fallback_local=True)
    if stdout:
        sys.stdout.write(stdout)
    return 0


__all__ = ["DEGRADED_MARKER", "degrade_to_noop"]
