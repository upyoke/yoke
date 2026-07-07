"""Offer-envelope merge: preserve non-offer-owned keys across writes.

``harness_sessions.offer_envelope`` is a JSON blob with multiple writers.
The session-offer code path writes per-offer identity/step fields; other
code paths (chain skip memory, chain checkpoint, codex thread id,
execution-scope scratch) deposit cross-offer state that must survive
between offers. This module merges per-offer fields over the existing
envelope so unknown keys, preserved cross-offer keys, and offer-owned
keys all land with the intended semantics.

The merge is value-level (``dict.update``), not deep — every top-level
envelope key is independent. The two named sets (``OFFER_WRITE_OWNED_KEYS``,
``PRESERVED_KEYS``) are documentation and lint anchors, not runtime gates:
``merge_offer_envelope`` already preserves every key the per-offer dict
omits, so adding a future preserved key is a one-line edit to the
``PRESERVED_KEYS`` set plus matching coverage in
``runtime/api/test_sessions_offer_envelope_preservation.py``.

The function tolerates missing, empty-string, malformed-JSON, and
non-dict existing envelopes by returning the per-offer dict unchanged.
``harness_sessions.offer_envelope`` is ``TEXT``/JSON; readers
(``read_chain_checkpoint``, ``read_chain_skip_memory``,
``frontier_recent_owner._checkpoint_outcome``, the route-defense
exclusion path) all tolerate malformed input, so this merger preserves
the same robustness contract.
"""

from __future__ import annotations

import json
from typing import Any, Dict, FrozenSet, Optional

# Keys the session-offer write owns. Per-offer values overwrite any
# existing value when present in the per-offer dict; they are preserved
# (alongside everything else) when the per-offer dict omits them — for
# example, ``runtime_session_id`` is only written when the executor is
# Codex AND ``CODEX_THREAD_ID`` is set, so a non-Codex offer that
# follows a Codex offer must not clobber the prior value.
OFFER_WRITE_OWNED_KEYS: FrozenSet[str] = frozenset({
    "session_id",
    "executor",
    "provider",
    "model",
    "workspace",
    "execution_lane",
    "capabilities",
    "step",
    "supported_paths",
    "max_chain_steps",
    "runtime_session_id",
})

# Cross-offer keys explicitly written by other code paths between
# offers. The merger preserves these regardless of presence in the
# per-offer dict (per-offer code never names them, so ``dict.update``
# leaves them intact).
#
# - ``chain_skip_memory``: appended by
#   ``sessions_queries_chain.append_chain_skip_entry`` so the next
#   offer in a chain dedups already-skipped items.
# - ``chain_checkpoint``: written by
#   ``sessions_queries_chain.update_chain_checkpoint`` and read by
#   bounded-resume guards and route-defense classification.
# - ``execution_scope``: written by
#   ``session_execution_scope._apply_transition`` to remember whether
#   the session is operating on main or inside a worktree.
PRESERVED_KEYS: FrozenSet[str] = frozenset({
    "chain_checkpoint",
    "chain_skip_memory",
    "execution_scope",
})


def merge_offer_envelope(
    existing_blob: Optional[str], per_offer: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge per-offer identity/step fields over the existing envelope.

    Preserves cross-offer state written by other code paths between
    offers (``chain_skip_memory``, ``chain_checkpoint``,
    ``execution_scope``, ``runtime_session_id`` when omitted from
    ``per_offer``, etc.) while letting per-offer identity keys
    overwrite their prior values.

    A missing, empty, malformed, or non-dict existing blob is treated
    as no prior state — the merge returns the per-offer dict unchanged.
    """
    if existing_blob:
        try:
            parsed = json.loads(existing_blob)
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            merged = dict(parsed)
            merged.update(per_offer)
            return merged
    return dict(per_offer)


__all__ = [
    "OFFER_WRITE_OWNED_KEYS",
    "PRESERVED_KEYS",
    "merge_offer_envelope",
]
