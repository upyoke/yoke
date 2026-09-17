"""Measured ceilings for the instruction text a session receives at startup.

Three independent channels carry startup instructions into a model, and each
truncates on its own terms:

``inline_hook``
    The composed ``additionalContext`` (Cursor's ``additional_context``) one
    hook process returns. Bounded by
    :mod:`yoke_contracts.hook_inline_context`, whose ceilings are the vendor
    thresholds above which a harness persists the body to a file and shows a
    preview instead.

``root_rules``
    The rules files a harness reads before its first turn — ``AGENTS.md`` for
    every harness, plus ``.claude/rules/session.md`` for Claude. Bounded per
    harness: Codex injects its copy through a channel with a measured cut,
    while the others have none observed.

``agent_prompt``
    One rendered subagent body. No harness has been observed truncating one,
    so this channel is bounded by what the condensed corpus measures rather
    than by a cut point.

Two kinds of number appear here and they are not interchangeable:

*Truncation ceilings* are observed points past which text demonstrably does
not reach the model. :data:`ROOT_RULES_TRUNCATION_BYTES` is one, and so is
every entry in :mod:`yoke_contracts.hook_inline_context`.

*Ratchet budgets* are the measured size of an artifact that has already been
condensed. They carry no claim about where a harness truncates; they exist so
that regrowth has to be a deliberate decision with a number attached rather
than a slow drift back to an undeliverable payload. The packet budgets in
:mod:`yoke_core.domain.schema_api_context_seed` are ratchets.

Bytes are the enforced axis. Tokens are reported beside them through
:func:`estimated_tokens` because operators reason in tokens, but the estimate
is derived from the byte count by a fixed divisor, so a separate token budget
could never fail independently of the byte budget — enforcing both would be
duplicated state expressing one fact. Where a real tokenizer count is needed,
measure it; do not read this estimate as one.
"""

from __future__ import annotations


# Divisor for the reported token estimate. Four bytes per token is the
# standard rule of thumb for English prose plus code identifiers, which is
# what every budgeted surface here contains. It is an estimate, named once so
# no caller invents its own.
ESTIMATED_BYTES_PER_TOKEN = 4

# Root-rules ceilings, per harness, and the two are not the same kind of
# number. Codex injects ``AGENTS.md`` through a bounded channel: one injection
# was read cut mid-sentence at 32,770 delivered bytes, placing its real
# ceiling at the 32 KiB boundary just below. That is a truncation ceiling and
# the file must fit it.
#
# Claude and Cursor have no observed cut on this channel — a Claude session
# was observed receiving 157,991 bytes of rules verbatim — so their numbers
# are ratchets measured off the condensed files, not claims about where they
# truncate. Keeping the two kinds apart matters: calling an unmeasured
# ratchet a ceiling invites dropping a rule to satisfy a limit nothing has
# demonstrated, and calling a measured cut a ratchet invites shipping rules
# that do not arrive.
ROOT_RULES_TRUNCATION_BYTES = 32768

ROOT_RULES_BYTES: dict[str, int] = {
    # Measured: the condensed rules pair spends 43,041 bytes.
    "claude": 44000,
    "codex": ROOT_RULES_TRUNCATION_BYTES,
    "cursor": ROOT_RULES_TRUNCATION_BYTES,
}


def root_rules_bytes(harness_id: str) -> int:
    """Return the root-rules budget for one renderer harness id."""
    try:
        return ROOT_RULES_BYTES[harness_id]
    except KeyError as error:
        raise ValueError(f"unknown harness: {harness_id!r}") from error


# The three startup channels, in the order a session receives them.
STARTUP_CHANNELS: tuple[str, ...] = ("root_rules", "inline_hook", "agent_prompt")


# A fourth channel opens after startup: the file a session reads when it enters
# a `/yoke` command. That read is not a startup cost — it is paid once per
# invocation, and again on every phase the command routes through — so it is
# budgeted separately from the three above.
#
# A ratchet, not a truncation ceiling. Nothing has been observed cutting a
# skill read; the number is the measured size of the condensed entrypoints, so
# an entrypoint that grows past it has to say why. It bounds the ENTRYPOINT
# only. A phase reference is read when its phase arrives and is deliberately
# unbounded: the point of the split is that detail lives where it is needed,
# not that every file is small.
SKILL_ENTRYPOINT_BYTES = 8000


__all__ = [
    "ESTIMATED_BYTES_PER_TOKEN",
    "ROOT_RULES_BYTES",
    "ROOT_RULES_TRUNCATION_BYTES",
    "SKILL_ENTRYPOINT_BYTES",
    "STARTUP_CHANNELS",
    "budget_phrase",
    "estimated_tokens",
    "root_rules_bytes",
]


def estimated_tokens(byte_count: int) -> int:
    """Return the reported token estimate for *byte_count* delivered bytes.

    An estimate, not a tokenizer count — see this module's docstring.
    """
    if byte_count <= 0:
        return 0
    return (byte_count + ESTIMATED_BYTES_PER_TOKEN - 1) // ESTIMATED_BYTES_PER_TOKEN


def budget_phrase(byte_count: int, budget: int) -> str:
    """Render one usage-against-budget phrase in both bytes and tokens.

    Every refusal and report states both axes from this one helper, so an
    operator never has to convert between them and no two messages disagree
    about the estimate.
    """
    return (
        f"{byte_count} bytes (~{estimated_tokens(byte_count)} tokens) "
        f"against a budget of {budget} bytes "
        f"(~{estimated_tokens(budget)} tokens)"
    )
