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

Wheel-shipped home next to the ordering table it wraps: server-side
consumers (the doctor health checks) must resolve the chain on a
wheels-only install, where the repo-tree hook runner is absent. The
returned module ids are data — some (e.g. the lifecycle dispatch entry)
name repo-tree modules that only import inside a source checkout; the
runner's dynamic dispatch fails open per module where they are absent.

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
_LIFECYCLE_DISPATCH: tuple[str, ...] = (
    "runtime.harness.hook_runner.session_dispatch",
)

_LIFECYCLE_EVENTS: frozenset[str] = frozenset({
    "SessionStart",
    "UserPromptSubmit",
    "SessionEnd",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "Notification",
})


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
