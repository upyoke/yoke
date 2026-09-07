"""What a harness session actually consumed, in buckets a provider bills.

Every supported provider reports token consumption, and no two report it
in the same shape. Claude states uncached input, cache reads and cache
writes as separate fields and folds thinking into its output count. Codex
states one input number that *contains* its cached input, and one output
number that contains its reasoning. Summing either source's fields as
written double-counts, so a stored total has to name which reading it is.

The buckets here are therefore disjoint and billable: each token is
counted in exactly one of them, and each is priced at exactly one rate.
Every harness reader converts its source's semantics into these before
anything is stored, which is what lets one cost calculation serve all of
them. :data:`REASONING_BUCKET` is the deliberate exception — it is a
labelled *subset* of ``output``, recorded because an operator wants to see
it and never added to a total, because its tokens are already in output.

``status`` carries the other half of the honesty. A reading is complete
only when the artifact stated everything for the whole session; a source
that lost earlier history, or that cannot attribute its totals to the
model that produced them, is ``partial`` and says why. A harness that
states no usage at all is ``unavailable`` with its reason, never zero —
zero is a real measurement and would read as a session that ran free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence


#: The disjoint billable buckets, in the order every serializer uses. A
#: token counted here is counted once: ``input`` excludes cache reads and
#: cache writes, and ``output`` is the whole output count.
USAGE_BUCKETS = (
    "input",
    "cached_input",
    "cache_write",
    "cache_write_long",
    "output",
)

#: An informational subset of ``output``, never added to a token total and
#: never priced. Providers that separate reasoning bill it as output.
REASONING_BUCKET = "reasoning"

#: Every count a reading carries, buckets first.
USAGE_FIELDS = USAGE_BUCKETS + (REASONING_BUCKET,)

#: The artifact stated the whole session's consumption.
USAGE_COMPLETE = "complete"
#: Some of it: history that is gone, or totals that cannot be attributed.
USAGE_PARTIAL = "partial"
#: The harness states no usage anywhere machine-readable.
USAGE_UNAVAILABLE = "unavailable"

USAGE_STATUSES = (USAGE_COMPLETE, USAGE_PARTIAL, USAGE_UNAVAILABLE)


@dataclass(frozen=True)
class ModelUsage:
    """One model's consumption, already normalized into disjoint buckets."""

    model: str
    input: int = 0
    cached_input: int = 0
    cache_write: int = 0
    cache_write_long: int = 0
    output: int = 0
    reasoning: int = 0

    def billable_tokens(self) -> int:
        """Total tokens across the billable buckets, reasoning excluded."""
        return sum(getattr(self, bucket) for bucket in USAGE_BUCKETS)


@dataclass(frozen=True)
class SessionUsage:
    """One session's consumption as one artifact reading proved it.

    ``models`` is per-model because a session that switched models spent
    different money on each half, and a source that names the model per
    turn can say so. A source that reports only session totals records one
    entry and marks the reading ``partial`` when its model changed, rather
    than dividing totals it never measured.
    """

    status: str = USAGE_UNAVAILABLE
    reason: str = ""
    observed_at: str = ""
    source: str = ""
    models: tuple[ModelUsage, ...] = ()

    def billable_tokens(self) -> int:
        return sum(entry.billable_tokens() for entry in self.models)

    def measured(self) -> bool:
        """True when this reading counted something a provider served."""
        return self.status != USAGE_UNAVAILABLE and self.billable_tokens() > 0


def unavailable(reason: str, *, source: str = "") -> SessionUsage:
    """A reading that proved nothing, carrying why rather than zeros."""
    return SessionUsage(
        status=USAGE_UNAVAILABLE, reason=reason.strip(), source=source.strip()
    )


def normalize_count(value: Any) -> int:
    """Return a non-negative token count; anything else counts as none.

    A provider that omits a field, or states it as null, has not reported a
    negative number of tokens — it has reported nothing, and nothing adds
    zero. A negative value is a source defect and is treated the same way
    rather than subtracting from a total.
    """
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def add_usage(left: ModelUsage, right: ModelUsage) -> ModelUsage:
    """Fold two readings of the same model into one."""
    return ModelUsage(
        model=left.model,
        **{
            field: getattr(left, field) + getattr(right, field)
            for field in USAGE_FIELDS
        },
    )


def merge_models(entries: Sequence[ModelUsage]) -> tuple[ModelUsage, ...]:
    """Collapse repeated models into one entry each, first-seen order."""
    merged: dict[str, ModelUsage] = {}
    for entry in entries:
        existing = merged.get(entry.model)
        merged[entry.model] = add_usage(existing, entry) if existing else entry
    return tuple(merged.values())


def with_partial(usage: SessionUsage, reason: str) -> SessionUsage:
    """Downgrade a reading to ``partial``, keeping the first stated reason.

    Partiality only ever accumulates: a reader that discovers one gap and
    then another has not become more complete, and the first reason is the
    one nearest the cause.
    """
    if usage.status == USAGE_UNAVAILABLE:
        return usage
    return replace(
        usage,
        status=USAGE_PARTIAL,
        reason=usage.reason or reason.strip(),
    )


def usage_document(usage: SessionUsage) -> str:
    """Serialize one reading for the ``usage_totals`` column."""
    return json.dumps(
        {
            "status": usage.status,
            "reason": usage.reason,
            "observed_at": usage.observed_at,
            "source": usage.source,
            "models": [
                {
                    "model": entry.model,
                    **{field: getattr(entry, field) for field in USAGE_FIELDS},
                }
                for entry in usage.models
            ],
        }
    )


def usage_from_document(document: Any) -> Optional[SessionUsage]:
    """Read a stored ``usage_totals`` document, or ``None`` when unreadable.

    ``None`` is "this session has no reading", which every reader must
    distinguish from a reading of zero. A document that parses but states
    no recognized status is unreadable rather than assumed complete.
    """
    if isinstance(document, SessionUsage):
        return document
    block = document if isinstance(document, Mapping) else _parsed(document)
    if block is None:
        return None
    status = str(block.get("status") or "").strip()
    if status not in USAGE_STATUSES:
        return None
    raw_models = block.get("models")
    models = tuple(
        _model_from_block(entry)
        for entry in (raw_models if isinstance(raw_models, list) else ())
        if isinstance(entry, Mapping) and str(entry.get("model") or "").strip()
    )
    return SessionUsage(
        status=status,
        reason=str(block.get("reason") or ""),
        observed_at=str(block.get("observed_at") or ""),
        source=str(block.get("source") or ""),
        models=models,
    )


def _parsed(document: Any) -> Optional[Mapping[str, Any]]:
    """Parse a stored document, or ``None`` when it is not one."""
    if not isinstance(document, str) or not document.strip():
        return None
    try:
        block = json.loads(document)
    except (json.JSONDecodeError, TypeError):
        return None
    return block if isinstance(block, dict) else None


def _model_from_block(entry: Mapping[str, Any]) -> ModelUsage:
    return ModelUsage(
        model=str(entry.get("model") or "").strip(),
        **{field: normalize_count(entry.get(field)) for field in USAGE_FIELDS},
    )


__all__ = [
    "REASONING_BUCKET",
    "USAGE_BUCKETS",
    "USAGE_COMPLETE",
    "USAGE_FIELDS",
    "USAGE_PARTIAL",
    "USAGE_STATUSES",
    "USAGE_UNAVAILABLE",
    "ModelUsage",
    "SessionUsage",
    "add_usage",
    "merge_models",
    "normalize_count",
    "unavailable",
    "usage_document",
    "usage_from_document",
    "with_partial",
]
