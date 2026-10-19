"""Resolve model-specific effort thresholds and one-class older-model demotion."""

from dataclasses import dataclass
from yoke_contracts.model_reference import lookup_model_reference
from yoke_contracts.session_control.native_model_parsers import cursor_token_effort
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    NOT_REPORTED_EFFORT,
)

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
MODEL_CLASSES = {
    "anthropic": ("haiku", "sonnet", "opus", "fable"),
    "openai": ("luna", "terra", "sol", "astra"),
}


def normalized_effort(effort):
    value = str(effort or "").strip().lower()
    return "xhigh" if value == "extra-high" else value


def effort_ordinal(effort):
    value = normalized_effort(effort)
    return EFFORT_ORDER.index(value) if value in EFFORT_ORDER else None


def model_class(record):
    return next(
        (
            name
            for name in MODEL_CLASSES.get(record.provider, ())
            if name in record.model_id.split("-")
        ),
        None,
    )


def routing_model_of(
    served_model: str | None, requested_model: str | None
) -> str | None:
    """Return the model an option is matched against.

    A provider-attested model wins. Most sessions have none at registration,
    so the ask is the fallback, with its context-tier suffix removed because
    that suffix names a context window rather than a different model.
    """
    if served_model and served_model.strip():
        return served_model.strip()
    asked = (requested_model or "").strip()
    if asked.lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        asked = asked[: -len(CLAUDE_CONTEXT_TIER_SUFFIX)]
    return asked or None


def routing_effort_of(
    served_effort: str | None,
    requested_effort: str | None,
    served_model: str | None = None,
) -> str | None:
    """Return the effort an option is matched against, attested first."""
    for value in (
        served_effort,
        cursor_token_effort(served_model or ""),
        requested_effort,
    ):
        if value and value.strip():
            return value.strip().lower()
    return None


@dataclass(frozen=True)
class ModelLevelResolution:
    level: str | None
    model: str | None
    effort: str | None
    reason: str | None = None


def resolve_model_level(levels, *, model, effort, records):
    """Observed model facts decide membership; speed and launch labels do not."""
    record = lookup_model_reference(str(model or ""), records).record
    actual_effort = normalized_effort(effort or cursor_token_effort(str(model or "")))
    ordinal = effort_ordinal(actual_effort)
    if record is None:
        return ModelLevelResolution(None, None, actual_effort, "session_model_unknown")
    if not actual_effort:
        return ModelLevelResolution(
            None, record.model_id, actual_effort, "session_effort_unreported"
        )
    if actual_effort == NOT_REPORTED_EFFORT:
        # The harness was read and named no effort: the lowest level holds
        # the session, and the reason stays on it until the harness reports.
        return ModelLevelResolution(
            levels[0].name if levels else None,
            record.model_id,
            actual_effort,
            "session_effort_not_reported",
        )
    published = {normalized_effort(value) for value in record.reasoning_efforts}
    if ordinal is None or actual_effort not in published:
        return ModelLevelResolution(
            None, record.model_id, actual_effort, "session_effort_unpublished"
        )
    entries = [entry for level in levels for entry in level.options]
    placed = {
        lookup_model_reference(entry.model, records).record.model_id
        for entry in entries
        if lookup_model_reference(entry.model, records).record
    }
    effective_model = record.model_id
    if effective_model not in placed and record.replacement_model_id:
        classes = MODEL_CLASSES.get(record.provider, ())
        family = model_class(record)
        if family not in classes or classes.index(family) == 0:
            return ModelLevelResolution(
                None, effective_model, actual_effort, "session_older_model_bottom_class"
            )
        lower_class = classes[classes.index(family) - 1]
        targets = {
            candidate.model_id
            for candidate in records
            if candidate.model_id in placed
            and candidate.provider == record.provider
            and model_class(candidate) == lower_class
            and not candidate.replacement_model_id
        }
        if len(targets) != 1:
            return ModelLevelResolution(
                None,
                effective_model,
                actual_effort,
                "session_demotion_target_unavailable",
            )
        effective_model = targets.pop()
    for level in reversed(levels):
        for entry in level.options:
            candidate = lookup_model_reference(entry.model, records).record
            threshold = effort_ordinal(entry.min_effort)
            if (
                candidate
                and candidate.model_id == effective_model
                and threshold is not None
                and ordinal >= threshold
            ):
                return ModelLevelResolution(level.name, effective_model, actual_effort)
    return ModelLevelResolution(
        None, effective_model, actual_effort, "session_below_minimum_effort"
    )
