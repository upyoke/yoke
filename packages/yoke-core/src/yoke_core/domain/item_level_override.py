"""The ``level`` item-posture key: one item's override of its stage level.

An override is ``{shift, min, max, reason}`` stored under ``level`` in
``items.workflow_posture``. ``shift`` moves the stage level up (positive) or
down (negative) by that many levels; ``min`` and ``max`` name levels the
result is clamped to. At least one of the three is required, and ``reason``
always is: it is the only record of why this item launches away from its
stage default. Level names are checked against the levels the item's project
reads, so an override can never name a level a launch cannot resolve.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.universe_levels import effective_levels

LEVEL_POSTURE_KEY = "level"
_KEYS = frozenset({"shift", "min", "max", "reason"})


class LevelOverrideError(ValueError):
    """Raised when a ``level`` posture value is malformed."""


def _level_name(raw: Any, *, field: str, names: tuple[str, ...]) -> str:
    name = str(raw or "").strip().upper()
    if name not in names:
        raise LevelOverrideError(
            f"level override {field} {raw!r} is not a level this project reads; "
            f"name one of: {', '.join(names)}"
        )
    return name


def validate_level_override(conn: Any, *, project_id: int, raw: Any) -> dict[str, Any]:
    """Return the normalized override, or refuse naming the correction."""
    if not isinstance(raw, Mapping):
        raise LevelOverrideError(
            "level posture must be an object: "
            '{"shift": N, "min": LEVEL, "max": LEVEL, "reason": "..."}'
        )
    unknown = set(raw) - _KEYS
    if unknown:
        raise LevelOverrideError(
            f"level posture has unknown keys {sorted(unknown)}; "
            f"allowed: {sorted(_KEYS)}"
        )
    reason = str(raw.get("reason") or "").strip()
    if not reason:
        raise LevelOverrideError(
            "level posture requires a non-empty reason saying why this item "
            "launches away from its stage level"
        )
    if not {"shift", "min", "max"} & set(raw):
        raise LevelOverrideError(
            "level posture needs at least one of shift, min, or max; clear the "
            "key instead of storing an override that changes nothing"
        )
    levels, _source = effective_levels(conn, int(project_id))
    names = tuple(level.name for level in levels)
    out: dict[str, Any] = {"reason": reason}
    if "shift" in raw:
        shift = raw["shift"]
        if isinstance(shift, bool) or not isinstance(shift, int) or shift == 0:
            raise LevelOverrideError(
                "level override shift must be a non-zero integer (levels up, "
                "or negative for down); omit it for no shift"
            )
        out["shift"] = shift
    for field in ("min", "max"):
        if field in raw:
            out[field] = _level_name(raw[field], field=field, names=names)
    if "min" in out and "max" in out:
        if names.index(out["min"]) > names.index(out["max"]):
            raise LevelOverrideError(
                f"level override min {out['min']} is above max {out['max']}; "
                f"levels run lowest first: {', '.join(names)}"
            )
    return out


def describe_level_override(posture: Mapping[str, Any] | None) -> str:
    """One-line reading of an item's override, or ``""`` when it has none."""
    override = (posture or {}).get(LEVEL_POSTURE_KEY)
    if not isinstance(override, Mapping):
        return ""
    parts = []
    if override.get("shift"):
        parts.append(f"shift {int(override['shift']):+d}")
    for field in ("min", "max"):
        if override.get(field):
            parts.append(f"{field} {override[field]}")
    reason = str(override.get("reason") or "").strip()
    return f"level {' · '.join(parts)}" + (f" ({reason})" if reason else "")


def resolve_level_override(
    conn: Any, *, project_id: int, baseline_level: str, override: Any = None
) -> dict[str, Any]:
    """Apply one item's shift and bounds to a named launch baseline once.

    Automatic stage defaults and stage readouts share this calculation.
    Explicit level and exact surface/model requests bypass the item default.
    """
    levels, _source = effective_levels(conn, int(project_id))
    names = tuple(level.name for level in levels)
    name = _level_name(baseline_level, field="baseline", names=names)
    normalized = (
        validate_level_override(conn, project_id=project_id, raw=override)
        if override is not None
        else {}
    )
    index = names.index(name) + normalized.get("shift", 0)
    low = names.index(normalized["min"]) if "min" in normalized else 0
    high = names.index(normalized["max"]) if "max" in normalized else len(names) - 1
    baseline = levels[names.index(name)]
    selected = levels[max(low, min(high, index))]
    return {
        "baseline_level": baseline.name,
        "baseline_glyph": baseline.glyph,
        "level": selected.name,
        "glyph": selected.glyph,
        "override": normalized,
    }


__all__ = [
    "LEVEL_POSTURE_KEY",
    "LevelOverrideError",
    "describe_level_override",
    "resolve_level_override",
    "validate_level_override",
]
