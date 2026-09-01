"""Where each harness states the context window it is actually serving.

``harness_sessions.context_window_tokens`` promises a measurement, so only
a surface that names the number outright may fill it. A window derived from
consumption — a usage high-water mark, a cache-read total, a percentage
read backwards — would file a guess under that promise, and the split
between the served and requested columns exists precisely to keep guesses
out. A harness with no such surface attests nothing and says so here.

That declaration is not documentation alone. Where the window is written
matters as much as whether it exists: a harness that records it from a
different process than the one naming its model can produce it *after* the
model is known, so the relay has to keep looking for it even once the
expensive artifact reads are finished. :data:`SEPARATELY_RECORDED_WINDOW_HARNESSES`
names those harnesses.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.harness_family_identity import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
)

#: The first-class served-window surface per harness family, or ``""`` for
#: a family that states the window nowhere machine-readable.
#:
#: Claude states it in the JSON it pipes to the configured status line
#: command, documented as "Maximum context window size in tokens. 200000 by
#: default, or 1000000 for models with extended context". Its hook payloads
#: carry session id, transcript path, permission mode and effort but never
#: the window, and its transcript rows carry per-message usage but never
#: the window, so the status line is the entire Claude channel. Codex
#: states it in its rollout, which is why Codex was the only attesting
#: harness before the status line was wired up. Cursor states it nowhere —
#: see :data:`CURSOR_CONTEXT_WINDOW_DEFERRAL`. Its empty entry is what makes
#: that a declared deferral rather than a branch someone forgot to write.
SERVED_CONTEXT_WINDOW_SOURCES: Mapping[str, str] = {
    CLAUDE_FAMILY: "status line JSON context_window.context_window_size",
    CODEX_FAMILY: "rollout turn_context.model_context_window",
    CURSOR_FAMILY: "",
}

#: Why Cursor's served window stays unattested, recorded so the next reader
#: inherits the search instead of repeating it. Its conversation store
#: (``~/.cursor/chats/<workspace>/<conversation>/store.db``) names only the
#: served variant, in ``providerOptions.cursor.modelName``; that store's
#: ``meta`` row carries the agent id, title, mode and encryption key and no
#: model facts at all; ``cursor-agent --list-models`` spells "1M" in human
#: display labels only; and ``cli-config.json`` records a ``context`` model
#: parameter that is the operator's selection — an ask, and an ask never
#: becomes a served fact. Re-check the store schema when Cursor changes it.
CURSOR_CONTEXT_WINDOW_DEFERRAL = (
    "cursor states no served context window in any machine-readable "
    "surface: its conversation store records only modelName, its model "
    "listing spells the window in display labels, and the context model "
    "parameter in cli-config.json is a request rather than an attestation"
)


def attests_context_window(harness_id: object) -> bool:
    """True when *harness_id* has a first-class served-window source."""
    return bool(SERVED_CONTEXT_WINDOW_SOURCES.get(str(harness_id or "").strip()))


#: Harnesses whose served window is written by a different process than the
#: one that names their model, and so can arrive after it.
#:
#: Only Claude: its model comes from the transcript the session itself
#: writes, while its window comes from the status line, a separate
#: short-lived process Claude runs on its own schedule. Codex writes both
#: into one rollout, so a read that finds its model has already found its
#: window; Cursor records neither a window nor anything to wait for.
#:
#: The distinction earns its place by bounding work. Resolving a served
#: model costs a transcript scan or a store query, so the relay stops once
#: a model is proven — and a harness listed here needs its window looked
#: for past that point, which is only affordable because that lookup is
#: opening one small recorded file rather than re-reading an artifact.
SEPARATELY_RECORDED_WINDOW_HARNESSES = frozenset({CLAUDE_FAMILY})


def records_window_separately(harness_id: object) -> bool:
    """True when *harness_id*'s window can arrive after its model."""
    return str(harness_id or "").strip() in SEPARATELY_RECORDED_WINDOW_HARNESSES


__all__ = [
    "CURSOR_CONTEXT_WINDOW_DEFERRAL",
    "SEPARATELY_RECORDED_WINDOW_HARNESSES",
    "SERVED_CONTEXT_WINDOW_SOURCES",
    "attests_context_window",
    "records_window_separately",
]
