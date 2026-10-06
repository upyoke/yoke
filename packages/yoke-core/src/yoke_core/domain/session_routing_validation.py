"""The write boundary for a project's ``session-routing`` settings.

Everything downstream of storage reads this document defensively — a
malformed rule degrades a session to its harness default rather than
refusing to register it — which is only safe because nothing malformed
reaches storage in the first place. This module is that guarantee, and it
runs from the one canonicalization hook every capability writer passes
through, so ``set``, ``merge``, and a create all get the same answer.

Refusals name the settings path that has to change and what to change it
to. A lane glyph is the clearest case: the terminal-safe convention is not
guessable from the value an operator typed, so the refusal quotes the
offending code point and offers glyphs that work.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.lane_glyph import LaneGlyphError, validate_lane_glyph
from yoke_contracts.session_lane import (
    lane_is_unresolved,
    retired_lane_setting_keys,
    retired_process_offer_keys,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_routing_rules import LaneRuleError, parse_lane_rules


MAX_LANE_LABEL_CHARS = 32
"""Longest lane label the board's session column can carry without the
label alone deciding the width of every row."""


class SessionRoutingSettingsError(ValueError):
    """Raised when a ``session-routing`` document cannot be stored as written."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def _lane_identity_error(lane: object) -> Optional[str]:
    if not isinstance(lane, str) or not lane.strip():
        return "a lane identity must be a non-empty string"
    lane_id = lane.strip()
    if lane_is_unresolved(lane_id):
        return (
            f"{lane_id!r} is the reserved identity for a session whose lane "
            "nothing resolved, so it cannot name a real lane. Pick another "
            "identity"
        )
    normalized = "".join(char if char.isalnum() else "_" for char in lane_id).upper()
    if lane_id != normalized:
        return (
            f"{lane_id!r} is stored as {normalized!r} by routing, so the two "
            "spellings would name one lane under two names. Write the "
            "identity as uppercase letters, digits, and underscores"
        )
    return None


def _require_lane_identity(lane: object, *, field: str) -> str:
    error = _lane_identity_error(lane)
    if error is not None:
        raise SessionRoutingSettingsError(error + ".", field=field)
    return str(lane).strip()


def _validate_lane_metadata(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate lane presentation and return the lanes it declares."""
    raw = settings.get("lane_metadata")
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise SessionRoutingSettingsError(
            "must be an object keyed by lane identity, each value carrying "
            f"that lane's label and glyph; got {type(raw).__name__}.",
            field="lane_metadata",
        )
    labels: dict[str, str] = {}
    lanes: list[str] = []
    for lane, entry in raw.items():
        field = f"lane_metadata.{lane}"
        lane_id = _require_lane_identity(lane, field="lane_metadata")
        if not isinstance(entry, Mapping):
            raise SessionRoutingSettingsError(
                "must be an object with a label and a glyph; got "
                f"{type(entry).__name__}.",
                field=field,
            )
        unknown = sorted(set(entry) - {"label", "glyph"})
        if unknown:
            raise SessionRoutingSettingsError(
                f"carries unsupported key(s) {', '.join(unknown)}; lane "
                "presentation is a label and a glyph.",
                field=field,
            )
        label = entry.get("label", lane_id)
        if not isinstance(label, str) or not label.strip():
            raise SessionRoutingSettingsError(
                "label must be a non-empty string.", field=f"{field}.label"
            )
        label = label.strip()
        if label != label.upper():
            raise SessionRoutingSettingsError(
                f"label {label!r} must be uppercase — lane labels are read as "
                f"identities on the board. Use {label.upper()!r}.",
                field=f"{field}.label",
            )
        if len(label) > MAX_LANE_LABEL_CHARS:
            raise SessionRoutingSettingsError(
                f"label {label!r} is {len(label)} characters; the board's "
                f"session column holds at most {MAX_LANE_LABEL_CHARS}.",
                field=f"{field}.label",
            )
        claimed_by = labels.get(label)
        if claimed_by is not None:
            raise SessionRoutingSettingsError(
                f"label {label!r} is already used by lane {claimed_by!r}. Two "
                "lanes reading the same on every surface cannot be told "
                "apart; give this one its own label.",
                field=f"{field}.label",
            )
        labels[label] = lane_id
        if "glyph" in entry:
            try:
                validate_lane_glyph(entry.get("glyph"), field="glyph")
            except LaneGlyphError as exc:
                raise SessionRoutingSettingsError(
                    str(exc), field=f"{field}.glyph"
                ) from exc
        lanes.append(lane_id)
    return tuple(lanes)


EXECUTOR_LANE_PREFIX = "executor_default_lane_"


def _lane_reference_entries(settings: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Yield ``(field, lane)`` for every harness-default lane reference."""
    entries: list[tuple[str, Any]] = []
    grouped = settings.get("executor_default_lanes")
    if grouped is not None:
        if not isinstance(grouped, Mapping):
            raise SessionRoutingSettingsError(
                "must be an object mapping an executor or executor prefix to "
                f"a lane; got {type(grouped).__name__}.",
                field="executor_default_lanes",
            )
        entries.extend(
            (f"executor_default_lanes.{selector}", lane)
            for selector, lane in grouped.items()
        )
    entries.extend(
        (str(key), value)
        for key, value in settings.items()
        if isinstance(key, str)
        and key.startswith(EXECUTOR_LANE_PREFIX)
        and key != EXECUTOR_LANE_PREFIX
    )
    return tuple(entries)


def _validate_lane_references(
    entries: tuple[tuple[str, Any], ...], *, declared: Iterable[str]
) -> None:
    declared_lanes = set(declared)
    for field, lane in entries:
        if not isinstance(lane, str) or lane.strip() not in declared_lanes:
            raise SessionRoutingSettingsError(
                f"routes to lane {lane!r}, which this project does not "
                f"declare. Declared lanes are "
                f"{', '.join(sorted(declared_lanes)) or '(none)'}; declare "
                "the lane in lane_metadata first.",
                field=field,
            )


def validate_session_routing_settings(settings: Mapping[str, Any]) -> None:
    """Refuse a ``session-routing`` document that cannot be routed on.

    Validates the document as a whole rather than the keys one writer
    happened to touch, because a merge that adds one rule can only be
    judged against the lane_metadata identities the document declares.
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
            "execution lanes group sessions by harness and model. "
            "Use lane_metadata to declare lanes and workflow bindings to "
            "select stage skills.",
            field=", ".join(retired),
        )
    declared = _validate_lane_metadata(settings)
    _validate_lane_references(_lane_reference_entries(settings), declared=declared)
    try:
        parse_lane_rules(settings.get("lane_rules"), declared_lanes=declared)
    except LaneRuleError as exc:
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
    "MAX_LANE_LABEL_CHARS",
    "SessionRoutingSettingsError",
    "validate_json_string",
    "validate_session_routing_settings",
]
