"""Preflight gate evaluation for the advance implementation entry.

Owns the pre-worktree refusal gates run before an item advances into
``implementing``: acting-session identity, upstream hard-block dependencies,
acceptance-criteria presence, File Budget, and path-claim spec coverage. Kept
separate from the orchestrator module so it stays within the authored-file
line cap.

The DB-backed gates route their reads through the
transport-aware ``call_dispatcher`` facade (registered
``advance.preflight.*`` internal functions) so the evaluation works over
an https control plane as well as an in-process local Postgres
connection. The gate ordering, short-circuit behavior, and operator-facing
narratives are constructed here client-side, unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import format_item_ref

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


IDENTITY_UNRESOLVED = "write-guard-identity-unresolved"
IDENTITY_MISMATCH = "write-guard-identity-mismatch"


def _probe_session_identity(
    declared_session_id: Optional[str],
) -> Tuple[str, str, str]:
    """Corroborate the claim owner through the write guards' resolver.

    ``--session-id`` is accepted only when the canonical ambient chain sees
    the same session. A flag alone cannot make later PreToolUse calls identify
    the process, so a missing or divergent ambient identity must stop before
    worktree preflight creates a claim or lane.
    """
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    ambient = (resolve_ambient_session_id() or "").strip()
    declared = (declared_session_id or "").strip()
    if ambient and (not declared or declared == ambient):
        return ambient, "", ""

    if not ambient:
        kind = IDENTITY_UNRESOLVED
        detail = "the canonical ambient chain returned no session id"
    else:
        kind = IDENTITY_MISMATCH
        detail = (
            f"declared session {declared!r} differs from the write-guard "
            f"session {ambient!r}"
        )
    narrative = (
        f"BLOCKED: {kind}: implementation entry refused before work-claim "
        f"or lane creation because {detail}. Repair the harness identity "
        "path consumed by the write guards (environment stamp, process-anchor "
        "registry, or Cursor conversation map), then retry. Do not guess or "
        "export a session id; --session-id must corroborate the same ambient "
        "session because later PreToolUse calls cannot observe the flag."
    )
    return "", kind, narrative


def _relay_gate(
    function_id: str, item_id: int, payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Evaluate one gate server-side through the transport-aware relay.

    Raises when the relay refuses so an unevaluable gate fails closed —
    a refusal gate must never be treated as passing.
    """
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload=payload or {},
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = (
            response.error.message if response.error else "gate evaluation failed"
        )
        raise RuntimeError(f"{function_id} failed ({code}): {message}")
    return response.result or {}


def _run_preflight_gates(item_id: int, *, force: bool) -> Tuple[bool, str]:
    """Hard-block dep + AC presence + spec coverage. Returns (ok, narrative)."""
    if force:
        return True, ""

    blockers = _relay_gate(
        "advance.preflight.hard_blocks", item_id,
        {"gate_filter": "activation"},
    ).get("blockers") or []
    if blockers:
        return False, "Blocked by dependencies:\n  " + "\n  ".join(blockers)

    ac = _relay_gate("advance.preflight.ac_presence", item_id)
    title = ac.get("title")
    canonical = int(ac.get("canonical") or 0)
    # No-conn fallback: this gate path must not open a bare local connect
    # (https control planes relay gate reads server-side). Prefer an
    # public_ref the relay already returned; otherwise format from the id.
    public_ref = (
        ac.get("public_ref")
        or format_item_ref(None, None, None, item_id=int(item_id))
    )
    if title is None:
        return False, f"{public_ref} not found in DB."
    if canonical <= 0:
        return False, (
            f"{public_ref} has no acceptance criteria. Add "
            f"`## Acceptance Criteria` with `- [ ] AC-N: ...` checkboxes."
        )

    budget = _relay_gate("advance.preflight.file_budget", item_id)
    if budget.get("verdict") != "pass":
        return False, f"BLOCKED: {budget.get('reason')}"

    cov = _relay_gate("advance.preflight.spec_coverage", item_id)
    if cov.get("is_blocked"):
        missing = cov.get("missing_paths") or []
        cov_ref = (
            cov.get("public_ref")
            or public_ref
        )
        return False, (
            f"BLOCKED: {cov_ref} File Budget lists "
            f"{len(missing)} path(s) not covered by any active "
            f"path_claim.\nMissing: " + ", ".join(missing)
        )
    return True, ""


__all__ = [
    "IDENTITY_MISMATCH",
    "IDENTITY_UNRESOLVED",
    "_probe_session_identity",
    "_run_preflight_gates",
]
