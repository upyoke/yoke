"""The write boundary for a project's ``session-routing`` settings.

Everything downstream of storage reads this document defensively — a
malformed rule degrades a session to its harness default rather than
refusing to register it — which is only safe because nothing malformed
reaches storage in the first place. This module is that guarantee, and it
runs from the one canonicalization hook every capability writer passes
through, so ``set``, ``merge``, and a create all get the same answer.

Refusals name the settings path that has to change and what to change it
to. A level glyph is the clearest case: the terminal-safe convention is not
guessable from the value an operator typed, so the refusal quotes the
offending code point and offers glyphs that work.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.glyph_contract import GlyphContractError, validate_glyph
from yoke_contracts.session_level import (
    EXECUTOR_DEFAULT_LEVEL_PREFIX,
    level_is_unresolved,
    renamed_routing_keys,
    retired_lane_setting_keys,
    retired_process_offer_keys,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_routing_rules import LevelRuleError, parse_level_rules


MAX_LEVEL_LABEL_CHARS = 32
"""Longest level label the board's session column can carry without the
label alone deciding the width of every row."""


class SessionRoutingSettingsError(ValueError):
    """Raised when a ``session-routing`` document cannot be stored as written."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def _level_identity_error(level: object) -> Optional[str]:
    if not isinstance(level, str) or not level.strip():
        return "a level identity must be a non-empty string"
    level_id = level.strip()
    if level_is_unresolved(level_id):
        return (
            f"{level_id!r} is the reserved identity for a session whose level "
            "nothing resolved, so it cannot name a real level. Pick another "
            "identity"
        )
    normalized = "".join(char if char.isalnum() else "_" for char in level_id).upper()
    if level_id != normalized:
        return (
            f"{level_id!r} is stored as {normalized!r} by routing, so the two "
            "spellings would name one level under two names. Write the "
            "identity as uppercase letters, digits, and underscores"
        )
    return None


def _require_level_identity(level: object, *, field: str) -> str:
    error = _level_identity_error(level)
    if error is not None:
        raise SessionRoutingSettingsError(error + ".", field=field)
    return str(level).strip()


def _validate_level_metadata(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate level presentation and return the levels it declares."""
    raw = settings.get("level_metadata")
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise SessionRoutingSettingsError(
            "must be an object keyed by level identity, each value carrying "
            f"that level's label and glyph; got {type(raw).__name__}.",
            field="level_metadata",
        )
    labels: dict[str, str] = {}
    levels: list[str] = []
    for level, entry in raw.items():
        field = f"level_metadata.{level}"
        level_id = _require_level_identity(level, field="level_metadata")
        if not isinstance(entry, Mapping):
            raise SessionRoutingSettingsError(
                "must be an object with a label and a glyph; got "
                f"{type(entry).__name__}.",
                field=field,
            )
        unknown = sorted(set(entry) - {"label", "glyph"})
        if unknown:
            raise SessionRoutingSettingsError(
                f"carries unsupported key(s) {', '.join(unknown)}; level "
                "presentation is a label and a glyph.",
                field=field,
            )
        label = entry.get("label", level_id)
        if not isinstance(label, str) or not label.strip():
            raise SessionRoutingSettingsError(
                "label must be a non-empty string.", field=f"{field}.label"
            )
        label = label.strip()
        if label != label.upper():
            raise SessionRoutingSettingsError(
                f"label {label!r} must be uppercase — level labels are read as "
                f"identities on the board. Use {label.upper()!r}.",
                field=f"{field}.label",
            )
        if len(label) > MAX_LEVEL_LABEL_CHARS:
            raise SessionRoutingSettingsError(
                f"label {label!r} is {len(label)} characters; the board's "
                f"session column holds at most {MAX_LEVEL_LABEL_CHARS}.",
                field=f"{field}.label",
            )
        claimed_by = labels.get(label)
        if claimed_by is not None:
            raise SessionRoutingSettingsError(
                f"label {label!r} is already used by level {claimed_by!r}. Two "
                "levels reading the same on every surface cannot be told "
                "apart; give this one its own label.",
                field=f"{field}.label",
            )
        labels[label] = level_id
        if "glyph" in entry:
            try:
                validate_glyph(entry.get("glyph"), field="glyph")
            except GlyphContractError as exc:
                raise SessionRoutingSettingsError(
                    str(exc), field=f"{field}.glyph"
                ) from exc
        levels.append(level_id)
    return tuple(levels)


def _level_reference_entries(
    settings: Mapping[str, Any],
) -> tuple[tuple[str, Any], ...]:
    """Yield ``(field, level)`` for every harness-default level reference."""
    entries: list[tuple[str, Any]] = []
    grouped = settings.get("executor_default_levels")
    if grouped is not None:
        if not isinstance(grouped, Mapping):
            raise SessionRoutingSettingsError(
                "must be an object mapping an executor or executor prefix to "
                f"a level; got {type(grouped).__name__}.",
                field="executor_default_levels",
            )
        entries.extend(
            (f"executor_default_levels.{selector}", level)
            for selector, level in grouped.items()
        )
    entries.extend(
        (str(key), value)
        for key, value in settings.items()
        if isinstance(key, str)
        and key.startswith(EXECUTOR_DEFAULT_LEVEL_PREFIX)
        and key != EXECUTOR_DEFAULT_LEVEL_PREFIX
    )
    return tuple(entries)


def _validate_level_references(
    entries: tuple[tuple[str, Any], ...], *, declared: Iterable[str]
) -> None:
    declared_levels = set(declared)
    for field, level in entries:
        if not isinstance(level, str) or level.strip() not in declared_levels:
            raise SessionRoutingSettingsError(
                f"routes to level {level!r}, which this project does not "
                f"declare. Declared levels are "
                f"{', '.join(sorted(declared_levels)) or '(none)'}; declare "
                "the level in level_metadata first.",
                field=field,
            )


def validate_session_routing_settings(settings: Mapping[str, Any]) -> None:
    """Refuse a ``session-routing`` document that cannot be routed on.

    Validates the document as a whole rather than the keys one writer
    happened to touch, because a merge that adds one rule can only be
    judged against the level_metadata identities the document declares.
    """
    if not isinstance(settings, Mapping):
        raise SessionRoutingSettingsError(
            f"settings must be a JSON object; got {type(settings).__name__}.",
            field="settings",
        )
    retired_process = retired_process_offer_keys(settings)
    if retired_process:
        raise SessionRoutingSettingsError(
            "process_offer_policy_retired: remove these settings keys. "
            "Steering assigns process work explicitly; session routing groups "
            "sessions by harness and model.",
            field=", ".join(retired_process),
        )
    retired = retired_lane_setting_keys(settings)
    if retired:
        raise SessionRoutingSettingsError(
            "lane_action_allowlists_retired: remove these settings keys; "
            "execution levels group sessions by harness and model. "
            "Use level_metadata to declare levels and workflow bindings to "
            "select stage skills.",
            field=", ".join(retired),
        )
    renamed = renamed_routing_keys(settings)
    if renamed:
        raise SessionRoutingSettingsError(
            "lane_routing_keys_renamed: execution lanes are now execution "
            "levels. Rename "
            + ", ".join(f"{old} to {new}" for old, new in sorted(renamed.items()))
            + " and write the document again.",
            field=", ".join(sorted(renamed)),
        )
    declared = _validate_level_metadata(settings)
    _validate_level_references(_level_reference_entries(settings), declared=declared)
    try:
        parse_level_rules(settings.get("level_rules"), declared_levels=declared)
    except LevelRuleError as exc:
        raise SessionRoutingSettingsError(str(exc), field=exc.field) from exc


def validate_json_string(raw_json: str) -> str:
    """Validate a ``session-routing`` document and return it canonicalized."""
    payload = json_helper.loads_text(raw_json)
    if not isinstance(payload, dict):
        raise SessionRoutingSettingsError(
            "settings must be a JSON object.", field="settings"
        )
    validate_session_routing_settings(payload)
    return json_helper.dumps_compact(payload)


__all__ = [
    "MAX_LEVEL_LABEL_CHARS",
    "SessionRoutingSettingsError",
    "validate_json_string",
    "validate_session_routing_settings",
]
