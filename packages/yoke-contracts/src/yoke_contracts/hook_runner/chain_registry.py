"""Chain registry — event/matcher -> ordered policy module list.

`chain_for(event_name, matcher)` is the runner's only chain-lookup surface.
For tool-shaped events (PreToolUse / PostToolUse / apply_patch) it delegates
to `yoke_contracts.hook_runner.hook_ordering.ordered_pipeline_for`, which is
the universal ordering source of truth shared across harnesses. For
harness-lifecycle events that have no policy chain today (`SessionStart`,
`UserPromptSubmit`, `SessionEnd`, `Stop`, `SubagentStop`, `PreCompact`,
`Notification`) the registry returns the same single dispatch entry the
existing `harness_hook_ordering` table records — so callers see one list
shape regardless of event family.

Wheel-shipped home next to the ordering table it wraps: installed engine
and client consumers must resolve the same chain without a source checkout.
Every returned module id therefore names a wheel-shipped module; dynamic
dispatch reports an import failure loudly if that invariant is broken.

Returned lists are fresh copies; mutating them does not leak back into the
underlying `HOOK_ORDERING` mapping.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for


# Lifecycle / notification events that route to the existing front-door
# session-hooks dispatch entry. Listed inline so the registry stays self-
# contained even when the underlying ordering table grows new matcher keys.
# `PreCompact` and `Notification` mirror Claude-only events whose
# chain-eligible content is empty today; we surface the same single
# dispatch entry so the runner can route them uniformly without a None
# check at the call site.
_LIFECYCLE_DISPATCH: tuple[str, ...] = ("yoke_core.hooks.session_dispatch",)

TERMINAL_HOOK_EVENTS: frozenset[str] = frozenset({"SessionEnd", "Stop", "SubagentStop"})

_LIFECYCLE_EVENTS: frozenset[str] = TERMINAL_HOOK_EVENTS | frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreCompact",
        "Notification",
    }
)

# The default event on which a client composes session orientation. Claude
# and Codex accept context on UserPromptSubmit; Cursor's model-visible startup
# channel is SessionStart instead. Both the product adapter and the shared
# composer call ``session_orientation_event`` so hot-path events can skip the
# engine without independently reconstructing that harness mapping.
SESSION_ORIENTATION_EVENT = "UserPromptSubmit"

# The canonical name for the event a harness fires once when a session
# opens, before any tool call. Several client-side paths key on it.
SESSION_START_EVENT = "SessionStart"


# The recurring context-bearing event that re-delivers an orientation block
# the startup event lost. Claude and Codex accept context on every prompt, so
# the startup event is its own second chance; Cursor's prompt hook answers
# block/allow only, leaving the tool-result event as its one repeating
# injection channel. Both mappings follow the harness manifests'
# ``inject_events`` capability rather than restating it.
SESSION_ORIENTATION_REDELIVERY_EVENT = "PostToolUse"


def session_orientation_event(*, cursor: bool = False) -> str:
    """Return the context-bearing startup event for one harness family."""
    return SESSION_START_EVENT if cursor else SESSION_ORIENTATION_EVENT


def session_orientation_redelivery_event(*, cursor: bool = False) -> str:
    """Return the event that re-delivers a missed orientation block."""
    if cursor:
        return SESSION_ORIENTATION_REDELIVERY_EVENT
    return SESSION_ORIENTATION_EVENT


def chain_for(event_name: str, matcher: str | None = None) -> list[str]:
    """Return the ordered policy module list for ``(event_name, matcher)``.

    The matcher argument is the tool name for PreToolUse/PostToolUse events
    (e.g. ``"Bash"``, ``"Edit"``, ``"apply_patch"``); ``None`` is treated
    as the registry's ``"_default"`` slot for events that do not split by
    tool. The returned list is always a fresh copy.
    """
    if event_name in _LIFECYCLE_EVENTS:
        # Ordering table already records the dispatch entry for the events
        # it knows about (SessionStart / UserPromptSubmit / SessionEnd /
        # Stop). For the ones it doesn't
        # (PreCompact / Notification) we fall back to the same lifecycle dispatch entry
        # so callers always get a non-empty list to iterate.
        chain = ordered_pipeline_for(event_name, "_default")
        if chain:
            return chain
        return list(_LIFECYCLE_DISPATCH)

    resolved = "_default" if matcher is None else matcher
    return ordered_pipeline_for(event_name, resolved)
