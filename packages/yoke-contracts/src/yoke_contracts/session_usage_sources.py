"""Where each harness states the tokens it consumed, or that it states none.

``harness_sessions.usage_totals`` promises a measurement, so only a
surface that counts tokens outright may fill it. A count inferred from
transcript length, message count, or a context-window percentage would
file an estimate under that promise. A harness with no such surface
attests nothing and says so here, so a missing reading reads as a
declared gap rather than a branch someone forgot to write.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.harness_family_identity import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
)


#: The first-class usage surface per harness family, or ``""`` for a
#: family that counts tokens nowhere machine-readable.
#:
#: Claude stamps a full ``message.usage`` block on every assistant row of
#: its session transcript, naming uncached input, cache reads, cache
#: writes split by cache lifetime, output, and the thinking tokens inside
#: that output. Codex writes a cumulative ``token_count`` event into its
#: rollout whose ``info.total_token_usage`` is the whole thread's
#: consumption to that point. Cursor states none — see
#: :data:`CURSOR_USAGE_DEFERRAL`.
SESSION_USAGE_SOURCES: Mapping[str, str] = {
    CLAUDE_FAMILY: "transcript assistant message.usage",
    CODEX_FAMILY: "rollout token_count info.total_token_usage",
    CURSOR_FAMILY: "",
}

#: Why Cursor's consumption stays unmeasured, recorded so the next reader
#: inherits the search instead of repeating it. Its conversation store
#: (``~/.cursor/chats/<workspace>/<conversation>/store.db``) holds only
#: ``blobs`` and ``meta``, and the blobs carry request payloads and
#: provider options with no usage block; its code-tracking database
#: (``~/.cursor/ai-tracking/ai-code-tracking.db``) counts edited lines and
#: AI-authorship percentages, never tokens; and its ACP session stores
#: mirror the same conversation blobs. Re-check when Cursor adds a usage
#: surface; until then a Cursor session reports this reason rather than a
#: total it cannot prove.
CURSOR_USAGE_DEFERRAL = (
    "cursor counts no tokens in any machine-readable surface: its "
    "conversation store holds request blobs with no usage block, and its "
    "code-tracking database counts edited lines rather than tokens"
)


def states_usage(harness_id: object) -> bool:
    """True when *harness_id* has a first-class token-count source."""
    return bool(SESSION_USAGE_SOURCES.get(str(harness_id or "").strip()))


def usage_source(harness_id: object) -> str:
    """Return the artifact *harness_id* states its consumption in."""
    return SESSION_USAGE_SOURCES.get(str(harness_id or "").strip(), "")


__all__ = [
    "CURSOR_USAGE_DEFERRAL",
    "SESSION_USAGE_SOURCES",
    "states_usage",
    "usage_source",
]
