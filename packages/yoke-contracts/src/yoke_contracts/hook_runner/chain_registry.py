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
# `PreCompact` (wired for Cursor) and `Notification` have no policy chain
# today; we surface the same single
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
# accepts context on UserPromptSubmit; Codex and Cursor also carry early
# orientation on SessionStart. Both the product adapter and the shared
# composer call ``session_orientation_event`` so hot-path events can skip the
# engine without independently reconstructing that harness mapping.
SESSION_ORIENTATION_EVENT = "UserPromptSubmit"

# The canonical name for the event a harness fires once when a session
# opens, before any tool call. Several client-side paths key on it.
SESSION_START_EVENT = "SessionStart"
# The canonical name for the event a harness fires when a session ends.
SESSION_END_EVENT = "SessionEnd"
# Cursor's only compaction signal; it fires before the context is summarised.
PRE_COMPACT_EVENT = "PreCompact"


def session_orientation_event(*, cursor: bool = False, executor: str = "") -> str:
    """Return the context-bearing startup event for one harness family."""
    return (
        SESSION_START_EVENT
        if cursor or executor == "codex"
        else SESSION_ORIENTATION_EVENT
    )


def session_orientation_redelivery_events(*, cursor: bool = False) -> frozenset[str]:
    """Return the recurring events that re-deliver a missed orientation block.

    Claude and Codex accept context on every prompt, so the prompt event
    repeats their delivery chance. Cursor's come from its surfaces' manifest
    ``inject_events``: the IDE's prompt hook orients the first chat in a new
    window, which fires no sessionStart, and tool results repeat the chance.
    """
    if not cursor:
        return frozenset({SESSION_ORIENTATION_EVENT})
    from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES

    return frozenset(
        event
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        if surface.startswith("cursor-")
        for event in capability.inject_events
        if event != SESSION_START_EVENT
    )


def session_orientation_events(*, cursor: bool = False, executor: str = "") -> frozenset[str]:
    """Return every event the orientation composer must see for one harness.

    Startup and repair events deliver the block; SessionStart and PreCompact
    can also reset it after a context restart, so the composer reads those
    even where they deliver nothing.
    """
    return frozenset(
        {
            session_orientation_event(cursor=cursor, executor=executor),
            SESSION_START_EVENT,
            PRE_COMPACT_EVENT,
        }
    ) | session_orientation_redelivery_events(cursor=cursor)


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


# Delivery, observation and guards that must inspect help opt out here.
HELP_EXEMPTION_OPTOUTS = frozenset({
    "yoke_core.hooks.session_message_delivery",
    "yoke_core.hooks.session_launch_attestation",
    "yoke_core.hooks.session_broker_wake",
    "yoke_core.hooks.heartbeat",
    "yoke_core.domain.observe_pre",
})


def help_only_chain(chain: list[str], event_name: str, help_only: bool) -> list[str]:
    """Apply the runner's print-only exemption before any guard is invoked."""
    if event_name != "PreToolUse" or not help_only:
        return chain
    return [module for module in chain if module in HELP_EXEMPTION_OPTOUTS]
