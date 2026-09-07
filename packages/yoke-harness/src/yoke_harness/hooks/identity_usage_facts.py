"""Session consumption on the relayed wire.

Usage rides the same hook events model facts do, and for the same reason:
only the machine running the harness can read the artifact that states
it. Unlike a served model, though, consumption never settles — it grows
for as long as the session runs, so every hook event carries the current
reading rather than stopping once one has landed.

That is affordable because a reading is incremental. The per-session
watermark means each event folds only the bytes the artifact gained since
the last one, and the value sent is the absolute total rather than a
delta, so a resend, a retry, or a relayed duplicate cannot inflate the
stored figure — the control plane replaces what it holds.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_usage_facts import usage_document


#: The wire and column name one reading travels under.
USAGE_WIRE_FIELD = "usage_totals"


def client_usage_facts(payload: dict[str, Any], executor: str) -> dict[str, Any]:
    """Return this session's current consumption reading for the wire.

    ``{}`` means the reading could not be produced at all, which is
    different from a reading that proved nothing: an unavailable reading
    still travels, because the reason it carries is what an operator sees
    instead of a blank total.
    """
    try:
        from yoke_harness.usage_attestation import attest_session_usage

        transcript = payload.get("transcript_path")
        usage = attest_session_usage(
            executor,
            payload,
            transcript_path=transcript if isinstance(transcript, str) else "",
        )
    except Exception:  # noqa: BLE001 — usage probes never break a hook
        return {}
    return {USAGE_WIRE_FIELD: usage_document(usage)}


__all__ = ["USAGE_WIRE_FIELD", "client_usage_facts"]
