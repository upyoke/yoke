"""Ordered execution bands containing model-specific minimum-effort rows."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_contracts.glyph_contract import GlyphContractError, validate_glyph
from yoke_contracts.model_level_resolution import (
    effort_ordinal,
    normalized_effort,
    resolve_model_level,
)
from yoke_contracts.model_reference import lookup_stem
from yoke_contracts.session_level import level_is_unresolved

LEVELS_KEY = "levels"


class LevelsError(ValueError):
    def __init__(self, code: str, message: str, *, field: str):
        super().__init__(f"{code}: {field}: {message}")
        self.code, self.field, self.detail = code, field, message


@dataclass(frozen=True)
class LevelEntry:
    model: str
    min_effort: str

    def payload(self):
        return {"model": self.model, "min_effort": self.min_effort}


@dataclass(frozen=True)
class Level:
    name: str
    glyph: str
    options: tuple[LevelEntry, ...]

    def payload(self):
        return {
            "name": self.name,
            "glyph": self.glyph,
            "options": [entry.payload() for entry in self.options],
        }


def level_name_error(name: object) -> Optional[str]:
    if not isinstance(name, str) or not name.strip():
        return "a level name must be a non-empty string"
    if level_is_unresolved(name):
        return f"{name.strip()!r} is reserved for an unresolved session; choose another name"
    normalized = "".join(c if c.isalnum() else "_" for c in name.strip()).upper()
    if name != normalized:
        return f"{name!r} must use uppercase letters, digits and underscores (for example {normalized!r})"
    return None


def _mapping(raw, keys, field, what):
    if not isinstance(raw, Mapping) or set(raw) - keys:
        raise LevelsError(
            "levels_document_invalid",
            f"{what} must carry only {', '.join(sorted(keys))}. Recovery: read levels get and correct the named row.",
            field=field,
        )
    return raw


def parse_levels(raw: Any, *, field: str = LEVELS_KEY) -> tuple[Level, ...]:
    """Validate the exact schema and strictly increasing thresholds per model."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise LevelsError(
            "levels_document_invalid",
            "Use a nonempty ordered list of levels.",
            field=field,
        )
    levels, thresholds = [], {}
    for index, raw_level in enumerate(raw):
        where = f"{field}[{index}]"
        document = _mapping(raw_level, {"name", "glyph", "options"}, where, "A level")
        name = document.get("name")
        error = level_name_error(name)
        if error:
            raise LevelsError("level_name_invalid", error, field=f"{where}.name")
        if any(level.name == name for level in levels):
            raise LevelsError(
                "level_name_duplicate",
                "Each level name appears once.",
                field=f"{where}.name",
            )
        try:
            glyph = validate_glyph(document.get("glyph"), field=f"{where}.glyph")
        except GlyphContractError as exc:
            raise LevelsError(
                "level_glyph_unsafe", str(exc), field=f"{where}.glyph"
            ) from exc
        rows = document.get("options")
        if not isinstance(rows, list) or not rows:
            raise LevelsError(
                "level_options_missing",
                "Each level needs model/min_effort rows.",
                field=f"{where}.options",
            )
        options, seen = [], set()
        for position, raw_entry in enumerate(rows):
            location = f"{where}.options[{position}]"
            entry = _mapping(
                raw_entry, {"model", "min_effort"}, location, "A level row"
            )
            model = entry.get("model")
            if (
                not isinstance(model, str)
                or not model.strip()
                or "*" in model
                or lookup_stem(model) != model
                or model.endswith("-thinking")
            ):
                raise LevelsError(
                    "level_model_invalid",
                    "Use one base model id without effort, speed, wildcard or context selectors.",
                    field=f"{location}.model",
                )
            effort = normalized_effort(entry.get("min_effort"))
            ordinal = effort_ordinal(effort)
            if ordinal is None:
                raise LevelsError(
                    "level_min_effort_invalid",
                    "Choose a published effort from none, minimal, low, medium, high, xhigh, max, ultra.",
                    field=f"{location}.min_effort",
                )
            if model in seen:
                raise LevelsError(
                    "level_option_duplicate",
                    "A model appears once within a level.",
                    field=location,
                )
            if model in thresholds and ordinal <= thresholds[model]:
                raise LevelsError(
                    "level_min_effort_order_invalid",
                    "A model's minimum effort must strictly increase with level. Raise this threshold or remove the conflicting row.",
                    field=location,
                )
            seen.add(model)
            thresholds[model] = ordinal
            options.append(LevelEntry(model, effort))
        levels.append(Level(name, glyph, tuple(options)))
    return tuple(levels)


def default_levels() -> tuple[Level, ...]:
    return parse_levels(list(DEFAULT_LEVELS))


def resolve_effective_levels(project_settings, universe_levels):
    if isinstance(project_settings, Mapping) and project_settings.get(LEVELS_KEY):
        return parse_levels(project_settings[LEVELS_KEY]), "project"
    if universe_levels:
        return parse_levels(universe_levels), "universe"
    return default_levels(), "default"


def levels_payload(levels):
    return [level.payload() for level in levels]


def level_for_session(levels, *, executor, model, reasoning_effort=None, records=()):
    """Registration executor metadata never changes model-level membership."""
    return resolve_model_level(
        levels, model=model, effort=reasoning_effort, records=records
    ).level


#: Why a session holds no level, as the board and session reads print it.
UNRESOLVED_LEVEL_REASONS = {
    "session_model_unreported": "model not reported yet",
    "session_model_unknown": "model not in the catalog",
    "session_effort_unpublished": "effort not published for its model",
    "session_older_model_bottom_class": "superseded model with no lower class",
    "session_demotion_target_unavailable": "no single lower-class model placed",
    "session_below_minimum_effort": "below every level's minimum effort",
}


def unresolved_level_reason(levels, *, model, effort, records):
    """The reason code a session with these facts resolves to no level."""
    if not str(model or "").strip():
        return "session_model_unreported"
    return resolve_model_level(
        levels, model=model, effort=effort, records=records
    ).reason


def level_presentation(levels, level, *, reason=None):
    """Label and glyph for a stored level; an unresolved one names its reason."""
    if level_is_unresolved(level):
        text = UNRESOLVED_LEVEL_REASONS.get(str(reason or ""), "")
        return {
            "label": f"no level: {text}" if text else "no level",
            "glyph": "",
            "reason": str(reason or ""),
        }
    name = str(level or "")
    return {
        "label": name,
        "glyph": next(
            (candidate.glyph for candidate in levels if candidate.name == name), ""
        ),
    }


__all__ = [
    "DEFAULT_LEVELS",
    "LEVELS_KEY",
    "Level",
    "LevelEntry",
    "LevelsError",
    "UNRESOLVED_LEVEL_REASONS",
    "default_levels",
    "level_for_session",
    "level_name_error",
    "level_presentation",
    "levels_payload",
    "parse_levels",
    "resolve_effective_levels",
    "unresolved_level_reason",
]
