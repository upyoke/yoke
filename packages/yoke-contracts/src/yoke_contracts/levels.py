"""Execution levels: ordered capability bands, each a list of launchable options.

A level is a name, a board glyph, and an ordered list of options; the order
of the levels list is the capability order, lowest first. An option is one
exact launchable selection — surface, model or native selector, reasoning
effort, and context window — validated against what that surface's CLI
accepts, so a wildcard or an effort the harness cannot pass never reaches
storage. A Cursor option may name a ``fallback`` on the same surface: the
selection used only when the option's own pool is exhausted.

The same options label sessions: a session is stamped with the level whose
option matches its harness, model, and (when known) effort. There is no
separately maintained rule list.

One document holds the levels for the whole universe; a project may carry an
override in its ``session-routing`` capability. Both stores hold the same
document shape, ``[{"name", "glyph", "options": [...]}, ...]``, and both are
validated by :func:`parse_levels`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_contracts.glyph_contract import GlyphContractError, validate_glyph
from yoke_contracts.session_control.model_selection import (
    SURFACE_EFFORT_LEVELS,
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)
from yoke_contracts.session_level import level_is_unresolved

LEVELS_KEY = "levels"
"""The key holding the levels document in both the universe and project stores."""

_LEVEL_KEYS = frozenset({"name", "glyph", "options"})
_OPTION_KEYS = frozenset(
    {"surface", "model", "reasoning_effort", "context_window_tokens", "fallback"}
)


class LevelsError(ValueError):
    """A levels document cannot be stored as written.

    ``code`` names the refusal; ``field`` is the document path to correct.
    """

    def __init__(self, code: str, message: str, *, field: str) -> None:
        super().__init__(f"{code}: {field}: {message}")
        self.code = code
        self.field = field
        self.detail = message


@dataclass(frozen=True)
class LevelOption:
    surface: str
    model: str
    reasoning_effort: str
    context_window_tokens: Optional[int] = None
    fallback: Optional["LevelOption"] = None

    @property
    def harness(self) -> str:
        return canonical_harness_id(self.surface)

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "surface": self.surface,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "context_window_tokens": self.context_window_tokens,
        }
        if self.fallback is not None:
            out["fallback"] = self.fallback.payload()
        return out


@dataclass(frozen=True)
class Level:
    name: str
    glyph: str
    options: tuple[LevelOption, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "glyph": self.glyph,
            "options": [option.payload() for option in self.options],
        }


def level_name_error(name: object) -> Optional[str]:
    """Explain why ``name`` cannot identify a level, or ``None`` when it can."""
    if not isinstance(name, str) or not name.strip():
        return "a level name must be a non-empty string"
    if level_is_unresolved(name):
        return (
            f"{name.strip()!r} is reserved for a session no level matched; "
            "choose another name"
        )
    normalized = "".join(c if c.isalnum() else "_" for c in name.strip()).upper()
    if name != normalized:
        return (
            f"{name!r} must be written as uppercase letters, digits, and "
            f"underscores (for example {normalized!r})"
        )
    return None


def _require_mapping(raw: Any, keys: frozenset[str], field: str, what: str):
    if not isinstance(raw, Mapping):
        raise LevelsError(
            "levels_document_invalid",
            f"{what} must be an object; got {type(raw).__name__}.",
            field=field,
        )
    unknown = sorted(set(raw) - keys)
    if unknown:
        raise LevelsError(
            "levels_document_invalid",
            f"{what} carries unsupported key(s) {', '.join(unknown)}; "
            f"allowed keys are {', '.join(sorted(keys))}.",
            field=field,
        )
    return raw


def _parse_option(raw: Any, field: str, *, allow_fallback: bool) -> LevelOption:
    mapping = _require_mapping(raw, _OPTION_KEYS, field, "a level option")
    surface = str(mapping.get("surface") or "").strip()
    if surface not in SURFACE_EFFORT_LEVELS:
        raise LevelsError(
            "level_option_surface_unsupported",
            f"surface {surface or '(missing)'!r} is not a launch surface; use "
            f"one of {', '.join(SURFACE_EFFORT_LEVELS)}.",
            field=f"{field}.surface",
        )
    model = str(mapping.get("model") or "").strip()
    effort = str(mapping.get("reasoning_effort") or "").strip().lower()
    if not model or "*" in model:
        raise LevelsError(
            "level_option_model_not_launchable",
            "an option names one exact model or native selector; wildcards "
            "and blanks are not launchable.",
            field=f"{field}.model",
        )
    if not effort:
        raise LevelsError(
            "level_option_effort_required",
            f"name the reasoning effort; {surface} accepts "
            f"{', '.join(SURFACE_EFFORT_LEVELS[surface])}.",
            field=f"{field}.reasoning_effort",
        )
    context = mapping.get("context_window_tokens")
    if context is not None and (
        isinstance(context, bool) or not isinstance(context, int)
    ):
        raise LevelsError(
            "level_option_context_invalid",
            "context_window_tokens must be a token count or null for the "
            "model's default window.",
            field=f"{field}.context_window_tokens",
        )
    try:
        validate_launch_model_selection(
            surface, LaunchModelSelection(model, effort, context)
        )
    except LaunchModelSelectionError as exc:
        raise LevelsError(exc.code, str(exc), field=field) from exc
    fallback = None
    if mapping.get("fallback") is not None:
        if not allow_fallback:
            raise LevelsError(
                "level_option_fallback_nested",
                "a fallback cannot carry its own fallback.",
                field=f"{field}.fallback",
            )
        fallback = _parse_option(
            mapping["fallback"], f"{field}.fallback", allow_fallback=False
        )
        if fallback.surface != surface:
            raise LevelsError(
                "level_option_fallback_surface",
                f"a fallback launches on the option's own surface ({surface}); "
                "list another surface as a separate option instead.",
                field=f"{field}.fallback.surface",
            )
    return LevelOption(surface, model, effort, context, fallback)


def parse_levels(raw: Any, *, field: str = LEVELS_KEY) -> tuple[Level, ...]:
    """Validate a levels document and return it, lowest level first."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise LevelsError(
            "levels_document_invalid",
            "levels must be a non-empty list of level objects, lowest first.",
            field=field,
        )
    levels: list[Level] = []
    selections: dict[tuple[str, str, str], str] = {}
    for index, entry in enumerate(raw):
        level_field = f"{field}[{index}]"
        mapping = _require_mapping(entry, _LEVEL_KEYS, level_field, "a level")
        name = mapping.get("name")
        error = level_name_error(name)
        if error is not None:
            raise LevelsError(
                "level_name_invalid", error + ".", field=f"{level_field}.name"
            )
        if any(level.name == name for level in levels):
            raise LevelsError(
                "level_name_duplicate",
                f"{name!r} is declared twice; each level appears once.",
                field=f"{level_field}.name",
            )
        try:
            glyph = validate_glyph(
                mapping.get("glyph"), field=f"{level_field}.glyph"
            )
        except GlyphContractError as exc:
            raise LevelsError(
                "level_glyph_unsafe", str(exc), field=f"{level_field}.glyph"
            ) from exc
        raw_options = mapping.get("options")
        if (
            not isinstance(raw_options, Sequence)
            or isinstance(raw_options, (str, bytes))
            or not raw_options
        ):
            raise LevelsError(
                "level_options_missing",
                "a level needs at least one launchable option.",
                field=f"{level_field}.options",
            )
        options = []
        for option_index, raw_option in enumerate(raw_options):
            option_field = f"{level_field}.options[{option_index}]"
            option = _parse_option(raw_option, option_field, allow_fallback=True)
            for selection in (option, option.fallback):
                if selection is None:
                    continue
                key = (selection.harness, selection.model, selection.reasoning_effort)
                if key in selections:
                    raise LevelsError(
                        "level_option_duplicate",
                        f"{selection.surface} {selection.model} at "
                        f"{selection.reasoning_effort} effort already belongs to "
                        f"{selections[key]}; one selection labels one level.",
                        field=option_field,
                    )
                selections[key] = str(name)
            options.append(option)
        levels.append(Level(str(name), glyph, tuple(options)))
    return tuple(levels)


def default_levels() -> tuple[Level, ...]:
    """The shipped scheme, parsed."""
    return parse_levels(list(DEFAULT_LEVELS))


def resolve_effective_levels(
    project_settings: Optional[Mapping[str, Any]],
    universe_levels: Any,
) -> tuple[tuple[Level, ...], str]:
    """Return the levels a project reads and where they came from.

    The project's ``session-routing`` override wins when it carries
    ``levels``; otherwise the stored universe document; otherwise the
    shipped scheme. The source is ``project``, ``universe``, or ``default``.
    """
    if isinstance(project_settings, Mapping) and project_settings.get(LEVELS_KEY):
        return parse_levels(project_settings[LEVELS_KEY]), "project"
    if universe_levels:
        return parse_levels(universe_levels), "universe"
    return default_levels(), "default"


def levels_payload(levels: Sequence[Level]) -> list[dict[str, Any]]:
    return [level.payload() for level in levels]


def level_for_session(
    levels: Sequence[Level],
    *,
    executor: Optional[str],
    model: Optional[str],
    reasoning_effort: Optional[str] = None,
) -> Optional[str]:
    """Return the level whose option matches this session, or ``None``.

    An option matches on harness family and exact model. An option at the
    session's own effort wins; otherwise (effort unknown, or one no option
    lists) the model alone decides. Either way the lowest matching level
    labels the session.
    """
    if not executor or not model:
        return None
    try:
        harness = canonical_harness_id(executor)
    except ValueError:
        return None
    effort = (reasoning_effort or "").strip().lower() or None
    by_model: Optional[str] = None
    for level in levels:
        for option in level.options:
            for selection in (option, option.fallback):
                if selection is None or (selection.harness, selection.model) != (
                    harness,
                    model,
                ):
                    continue
                if effort is None or selection.reasoning_effort == effort:
                    return level.name
                by_model = by_model or level.name
    return by_model


def level_presentation(levels: Sequence[Level], level: Optional[str]) -> dict[str, str]:
    """Return the label and glyph a stamped level renders with."""
    name = str(level or "")
    for candidate in levels:
        if candidate.name == name:
            return {"label": name, "glyph": candidate.glyph}
    return {"label": name, "glyph": ""}


__all__ = [
    "DEFAULT_LEVELS",
    "LEVELS_KEY",
    "Level",
    "LevelOption",
    "LevelsError",
    "default_levels",
    "level_for_session",
    "level_name_error",
    "level_presentation",
    "levels_payload",
    "parse_levels",
    "resolve_effective_levels",
]
