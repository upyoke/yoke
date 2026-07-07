"""Value-aware envelope-cap shrink for event context payloads.

When a built envelope exceeds the storage cap, the old behavior
replaced the ENTIRE context with ``{"_truncated": True}`` — losing the
identity scalars audits key on (``function``, ``request_id``, byte
counts) and silently disabling dispatcher idempotency-replay detection
for that call (the lookup scans ``context.request_id``). Routine
big-result calls (strategy render/ingest file texts) made that loss an
every-call event.

:func:`fit_envelope_context` shrinks per value instead: largest context
values are replaced one at a time with a
``{"_truncated_value": True, "_bytes": N}`` marker until the envelope
fits, so every small scalar survives untouched. The context-level
``"_truncated": True`` marker is kept for continuity with existing
audit queries. Only the pathological case (the envelope still over cap
with every value replaced) falls back to the old whole-context marker.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def _encoded_len(value: Any) -> int:
    return len(json.dumps(value).encode("utf-8"))


def fit_envelope_context(
    envelope: Dict[str, Any], *, max_envelope_bytes: int,
) -> None:
    """Shrink ``envelope['context']`` values in place until the envelope fits.

    No-op when the envelope is already within ``max_envelope_bytes``.
    Mutates only the ``context`` entry; every other envelope field is
    authoritative identity/attribution data and is never dropped here.
    """
    if _encoded_len(envelope) <= max_envelope_bytes:
        return
    context = envelope.get("context")
    if not isinstance(context, dict) or not context:
        envelope["context"] = {"_truncated": True}
        return

    shrunk: Dict[str, Any] = dict(context)
    shrunk["_truncated"] = True
    envelope["context"] = shrunk
    # Replace largest values first; stop as soon as the envelope fits so
    # small identity scalars are never touched.
    by_size = sorted(
        context, key=lambda key: _encoded_len(context[key]), reverse=True,
    )
    for key in by_size:
        if _encoded_len(envelope) <= max_envelope_bytes:
            return
        shrunk[key] = {
            "_truncated_value": True,
            "_bytes": _encoded_len(context[key]),
        }
    if _encoded_len(envelope) > max_envelope_bytes:
        envelope["context"] = {"_truncated": True}


__all__ = ["fit_envelope_context"]
