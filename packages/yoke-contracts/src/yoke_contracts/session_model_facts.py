"""The two kinds of model fact a harness session records.

A session carries an *ask* and a *served truth*, and they are not the same
value. The ask is what the launch plane or the operator's environment
requested — a Yoke launch's ``--model``, ``YOKE_MODEL``, a Claude context
tier selector. The served truth is what the provider reports it actually
ran, read back from the harness's own artifact after the fact.

Storing both is the point. The ask lands in the ``requested_*`` columns
and is always available; the plain columns hold only what an attestation
reader proved. ``None`` in a plain column means *not attested* — never
"same as requested". A reader that needs a value where none was attested
may show the requested one only while saying so.

The ask reaches those columns from two directions, because one of them
alone loses it. A session the operator started names its own ask in its
environment, which only that process can read. A launched session cannot
be trusted to: a harness that serves a launch from a pre-warmed process
pool hands the job to a process whose environment predates the launch, so
nothing the child sniffs mentions the model it was asked for. The control
plane holds that ask on the launch record and stamps it at binding —
:func:`requested_facts_of` derives the whole ask from the selector either
side holds, so both directions produce the same three columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.harness_family_identity import CURSOR_FAMILY


#: Reasoning-effort levels any supported harness names. Claude spells them
#: on ``--effort`` and in transcript rows, Codex in its rollout
#: ``turn_context.effort``, Cursor as the suffix of a flat variant name.
#: A value outside this set is recorded as-is only when a provider reported
#: it; nothing is derived from an unrecognized token.
REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "extra-high",
    "max",
    "ultra",
)

#: Claude spells its million-token context tier as a selector suffix on the
#: model string (``claude-opus-5[1m]``). The suffix is an ask: the served id
#: never carries it back, so it is requested-side only.
CLAUDE_CONTEXT_TIER_SUFFIX = "[1m]"
CLAUDE_CONTEXT_TIER_TOKENS = 1_000_000

#: Values a harness surface passes to mean "use whatever is configured"
#: rather than to name a model. A placeholder is never a served fact and
#: never a stated request: recording one would make every session that
#: emitted it look identical. Bracketed forms such as ``<synthetic>``
#: come from noninteractive SDK invocations before a concrete model exists.
PLACEHOLDER_MODEL_VALUES = frozenset({"", "default", "auto", "unknown"})


def is_placeholder_model(value: object) -> bool:
    """Return True when *value* names no model."""
    if not isinstance(value, str):
        return True
    normalized = value.strip().lower()
    if normalized in PLACEHOLDER_MODEL_VALUES:
        return True
    return normalized.startswith("<") and normalized.endswith(">")


#: The served half, in the order every serializer and column list uses.
SERVED_FIELDS = ("model", "reasoning_effort", "context_window_tokens")
#: The requested half, same order.
REQUESTED_FIELDS = (
    "requested_model",
    "requested_reasoning_effort",
    "requested_context_window_tokens",
)
MODEL_FACT_FIELDS = SERVED_FIELDS + REQUESTED_FIELDS


@dataclass(frozen=True)
class SessionModelFacts:
    """One session's model ask beside whatever the provider attested.

    Every field is optional because both halves arrive independently: the
    ask exists from the first hook event, while an attestation needs an
    artifact the harness has not necessarily written yet.
    """

    requested_model: Optional[str] = None
    requested_reasoning_effort: Optional[str] = None
    requested_context_window_tokens: Optional[int] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    context_window_tokens: Optional[int] = None

    def attested(self) -> bool:
        """True when a provider reported at least one served fact."""
        return any(
            value is not None
            for value in (
                self.model,
                self.reasoning_effort,
                self.context_window_tokens,
            )
        )


#: How a requested value is labelled when it stands in for a served one.
#: Every surface that falls back must say so; an unlabelled requested value
#: reads as a report of what ran, which is the confusion being removed.
REQUESTED_LABEL = " (requested)"
UNKNOWN_MODEL_DISPLAY = "unknown"


def model_display(facts: SessionModelFacts) -> str:
    """Render one session's model for a reader, never lying about which.

    The served id when a provider attested one. Otherwise the ask, plainly
    labelled as an ask. Otherwise ``"unknown"``, which is the honest answer
    for a session whose artifact has not been written yet.
    """
    if facts.model:
        return facts.model
    if facts.requested_model:
        return f"{facts.requested_model}{REQUESTED_LABEL}"
    return UNKNOWN_MODEL_DISPLAY


def served_model_or_none(value: object) -> Optional[str]:
    """Return a model a provider could have served, else ``None``.

    Beyond a placeholder, one more string reaches the served slot without
    being an attestation: a context tier selector. No provider response
    returns one, and a client older than this split ships its requested
    model under the plain key, so during the rollout window that is
    exactly what arrives. Storing it as served would assert a provider
    reported it.
    """
    if is_placeholder_model(value):
        return None
    text = str(value).strip()
    if text.lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        return None
    return text


def facts_arguments(facts: SessionModelFacts) -> list[str]:
    """Render the facts as CLI flags, one per stated column.

    An unstated fact ships no flag at all: an empty string on the wire
    would be indistinguishable from "the provider reported nothing", and
    the difference between those is the whole point of the split.
    """
    arguments: list[str] = []
    for field in MODEL_FACT_FIELDS:
        value = getattr(facts, field)
        if value is not None:
            arguments.extend([fact_flag(field), str(value)])
    return arguments


def fact_flag(field: str) -> str:
    """Return the CLI flag that carries ``field``."""
    return "--" + field.replace("_", "-")


def facts_from_mapping(source: Any) -> SessionModelFacts:
    """Read the facts out of any mapping keyed by the column names."""
    values = {}
    for field in SERVED_FIELDS + REQUESTED_FIELDS:
        raw = source.get(field) if hasattr(source, "get") else None
        if field.endswith("context_window_tokens"):
            values[field] = normalize_context_window_tokens(raw)
        elif field.endswith("reasoning_effort"):
            values[field] = normalize_reasoning_effort(raw)
        elif field == "model":
            # Guarded at the parser so the write path and the upgrade
            # probe inherit one rule rather than each carrying its own.
            values[field] = served_model_or_none(raw)
        elif is_placeholder_model(raw):
            # A placeholder names no model, so it is neither half of the
            # split — recording one would read as a real answer.
            values[field] = None
        else:
            values[field] = raw.strip()
    return SessionModelFacts(**values)


def normalize_reasoning_effort(value: object) -> Optional[str]:
    """Return a recognized effort level, or ``None``.

    An unrecognized token is dropped rather than stored: the column exists
    to answer "what effort served this session", and a value no harness
    names cannot answer it.
    """
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    return token if token in REASONING_EFFORT_VALUES else None


def normalize_context_window_tokens(value: object) -> Optional[int]:
    """Return a positive token count, or ``None`` for anything else."""
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def effort_suffix_of(model_name: object) -> Optional[str]:
    """Return the effort a flat variant name spells as its own suffix.

    Cursor encodes effort in the model name rather than in a separate
    parameter (``cursor-grok-4.6-xhigh``), so the name *is* the effort
    report. Longest suffix wins so ``-extra-high`` is not read as
    ``-high``. A name ending in nothing recognized yields ``None`` rather
    than a guess.
    """
    if not isinstance(model_name, str):
        return None
    token = model_name.strip().lower()
    for level in sorted(REASONING_EFFORT_VALUES, key=len, reverse=True):
        if token.endswith(f"-{level}"):
            return level
    return None


def requested_context_window_of(model_name: object) -> Optional[int]:
    """Return the context window a model selector asks for, or ``None``."""
    if not isinstance(model_name, str):
        return None
    if model_name.strip().lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        return CLAUDE_CONTEXT_TIER_TOKENS
    return None


#: Harness families whose model selector spells the effort as its own
#: suffix, so the name *is* the effort request. Cursor exposes no separate
#: effort parameter, which is why its variant names carry one. Reading a
#: suffix outside this set would invent an ask: a Codex family name ending
#: in ``-max`` names a model family, not a reasoning level.
NAME_ENCODED_EFFORT_HARNESSES = frozenset({CURSOR_FAMILY})


def requested_facts_of(model_name: object, *, harness_id: str) -> SessionModelFacts:
    """Return every ask a model selector states about itself.

    One derivation for both directions the ask arrives from — the child
    process reading its own environment, and the control plane stamping a
    launch's recorded model — so a launched session and an operator-started
    one on the same harness store the same three values. Channels a
    selector cannot carry (a Claude effort level, which rides the
    environment) stay ``None`` here and are filled by the caller that can
    read them.

    A placeholder names no model, so it states no ask at all.
    """
    if is_placeholder_model(model_name):
        return SessionModelFacts()
    model = str(model_name).strip()
    return SessionModelFacts(
        requested_model=model,
        requested_reasoning_effort=(
            effort_suffix_of(model)
            if harness_id in NAME_ENCODED_EFFORT_HARNESSES
            else None
        ),
        requested_context_window_tokens=requested_context_window_of(model),
    )


__all__ = [
    "CLAUDE_CONTEXT_TIER_SUFFIX",
    "CLAUDE_CONTEXT_TIER_TOKENS",
    "MODEL_FACT_FIELDS",
    "NAME_ENCODED_EFFORT_HARNESSES",
    "PLACEHOLDER_MODEL_VALUES",
    "REQUESTED_LABEL",
    "UNKNOWN_MODEL_DISPLAY",
    "PLACEHOLDER_MODEL_VALUES",
    "REASONING_EFFORT_VALUES",
    "REQUESTED_FIELDS",
    "SERVED_FIELDS",
    "SessionModelFacts",
    "effort_suffix_of",
    "fact_flag",
    "facts_arguments",
    "facts_from_mapping",
    "is_placeholder_model",
    "model_display",
    "normalize_context_window_tokens",
    "normalize_reasoning_effort",
    "requested_context_window_of",
    "requested_facts_of",
    "served_model_or_none",
]
