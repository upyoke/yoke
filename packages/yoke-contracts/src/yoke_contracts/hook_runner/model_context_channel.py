"""Which reply channel carries model-facing hook context, per harness.

A hook that has something to say to the model can say it two ways. Some
harnesses read the hook's raw stdout as context on the events that open or
close a turn; the rest read one structured reply envelope, and the decision
renderer folds advisory text into it.

The two are not interchangeable. Text appended beside a structured reply is
not parseable, so on an envelope harness it reaches no model at all - and
because the settlement layer only checks that the text made it into the
process's stdout, the delivery still settles as injected. That is a receipt
for a delivery that did not happen, which is worse than no delivery: the
control plane stops re-waking on the strength of it. Measured on
cursor-cli, where every real injection landed on the envelope event and
every stdout-channel one was recorded injected without reaching the model.

So the channel is a property of the harness, named once here, rather than a
Claude-shaped event set copied into each delivery module.
"""

from __future__ import annotations


STDOUT_CHANNEL = "stdout"
ADVISORY_CHANNEL = "additionalContext"

# Harness families whose hook stdout is read as model context. A family that
# is absent replies with a structured envelope and always uses the advisory
# channel; an unrecognized family is treated the same way, because dropping
# context with an honest receipt beats recording one that never arrived.
RAW_STDOUT_CONTEXT_FAMILIES = frozenset({"claude", "codex"})

# The events that open a turn, where a raw-stdout harness reads whatever the
# hook printed. Callers whose delivery also runs at turn end add ``Stop``.
SESSION_OPENING_STDOUT_EVENTS = frozenset({"SessionStart", "UserPromptSubmit"})


def model_context_channel(
    *,
    executor_family: str,
    event_name: str,
    stdout_events: frozenset[str],
) -> str:
    """Return the audit field name that carries this reply's model context.

    ``stdout_events`` is the caller's own scope: which events it delivers on
    where a raw-stdout harness reads stdout. The harness axis is this
    module's; the event axis belongs to the delivery module, because they do
    not all run on the same events.
    """
    if executor_family in RAW_STDOUT_CONTEXT_FAMILIES and event_name in stdout_events:
        return STDOUT_CHANNEL
    return ADVISORY_CHANNEL


__all__ = [
    "ADVISORY_CHANNEL",
    "RAW_STDOUT_CONTEXT_FAMILIES",
    "SESSION_OPENING_STDOUT_EVENTS",
    "STDOUT_CHANNEL",
    "model_context_channel",
]
