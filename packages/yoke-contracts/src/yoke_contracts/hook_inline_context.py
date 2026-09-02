"""Per-harness inline hook-context ceiling.

Harnesses persist composed ``additionalContext`` (or the Cursor
``additional_context`` sibling) up to a vendor threshold, then write the
rest to a file and show a preview from the top. Yoke therefore caps the
composed body using this contract rather than a literal copied into hook
code. Runtime readers import these numbers; rendered manifests echo them
so operators can see the same ceiling the composer uses.

Codex's default is the vendor ``additionalContextLimit`` already owned by
:mod:`yoke_contracts.codex_hook_trust`. Claude Code's observed persist
threshold is 8 KiB. Cursor has no measured persist threshold; it still
gets an explicit bound so composed context cannot grow without a name.
"""

from __future__ import annotations

from yoke_contracts.codex_hook_trust import DEFAULT_ADDITIONAL_CONTEXT_LIMIT
from yoke_contracts.executor_labels import canonical_harness_id


ENVELOPE_INLINE_CONTEXT_BYTES = 8192

INLINE_CONTEXT_BYTES: dict[str, int] = {
    "claude-code": ENVELOPE_INLINE_CONTEXT_BYTES,
    "codex": DEFAULT_ADDITIONAL_CONTEXT_LIMIT,
    "cursor": ENVELOPE_INLINE_CONTEXT_BYTES,
}


def inline_context_bytes_for_harness(harness_id: str) -> int:
    """Return the inline byte ceiling for a canonical or aliased harness id."""
    canonical = canonical_harness_id(harness_id)
    try:
        return INLINE_CONTEXT_BYTES[canonical]
    except KeyError as error:
        raise ValueError(f"unknown harness executor: {harness_id!r}") from error


__all__ = [
    "ENVELOPE_INLINE_CONTEXT_BYTES",
    "INLINE_CONTEXT_BYTES",
    "inline_context_bytes_for_harness",
]
