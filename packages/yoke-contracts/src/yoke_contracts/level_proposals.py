"""Propose catalog-driven edits to model/minimum-effort level rows."""

from __future__ import annotations
import copy
from yoke_contracts.levels import LevelsError, parse_levels
from yoke_contracts.model_level_resolution import effort_ordinal, normalized_effort
from yoke_contracts.model_reference import lookup_model_reference

CHANGE_KINDS = ("add", "move", "retire", "change")


def _record(model, records):
    return lookup_model_reference(model, records).record


def _selector(entry):
    return {
        "model": str(entry.get("model") or ""),
        "min_effort": normalized_effort(entry.get("min_effort")),
    }


def published_capability_conflicts(levels, records):
    conflicts, unverified = [], []
    for level in levels:
        for entry in level.options:
            where = {"level": level.name, **entry.payload()}
            record = _record(entry.model, records)
            if record is None or not record.reasoning_efforts:
                unverified.append(
                    {
                        **where,
                        "reason": "model or published efforts missing from catalog",
                    }
                )
            elif entry.min_effort not in {
                normalized_effort(value) for value in record.reasoning_efforts
            }:
                conflicts.append(
                    {
                        **where,
                        "field": "min_effort",
                        "value": entry.min_effort,
                        "published": list(record.reasoning_efforts),
                        "model_id": record.model_id,
                    }
                )
    return conflicts, unverified


def refuse_capability_conflicts(conflicts):
    if conflicts:
        first = conflicts[0]
        raise LevelsError(
            "level_min_effort_unpublished",
            f"{first['model']} at {first['level']} names unpublished effort {first['value']}. Recovery: choose a published threshold or correct catalog facts with yoke models publish.",
            field=f"{first['level']}.min_effort",
        )


def generate_level_changes(levels, records):
    changes = []
    for level in levels:
        for position, entry in enumerate(level.options):
            record = _record(entry.model, records)
            if record is None:
                continue
            target = (
                _record(record.replacement_model_id, records)
                if record.replacement_model_id
                else record
            )
            if target is None:
                continue
            effort = entry.min_effort
            published = sorted(
                {normalized_effort(value) for value in target.reasoning_efforts},
                key=lambda value: effort_ordinal(value) or 0,
            )
            if published and effort not in published:
                below = [
                    value
                    for value in published
                    if effort_ordinal(value) <= effort_ordinal(effort)
                ]
                effort = below[-1] if below else published[0]
            model = entry.model if target is record else target.model_id
            revised = {"model": model, "min_effort": effort}
            if revised == entry.payload():
                continue
            reason = f"{record.model_id} catalog successor or published effort changed"
            if model == entry.model:
                changes.append(
                    {
                        "kind": "change",
                        "option": entry.payload(),
                        "min_effort": effort,
                        "reason": reason,
                    }
                )
            else:
                changes.extend(
                    [
                        {"kind": "retire", "option": entry.payload(), "reason": reason},
                        {
                            "kind": "add",
                            "level": level.name,
                            "option": revised,
                            "position": position,
                            "reason": reason,
                        },
                    ]
                )
    return changes


def _unplaced(levels, records):
    placed = {
        _record(entry.model, records).model_id
        for level in levels
        for entry in level.options
        if _record(entry.model, records)
    }
    return [
        record
        for record in records
        if record.model_id not in placed and not record.replacement_model_id
    ]


def _model_row(record):
    return {
        "model_id": record.model_id,
        "provider": record.provider,
        "display_name": record.display_name,
    }


def unplaced_models(levels, records):
    """Current models no level places that a level row could place.

    A row needs a published minimum effort, so a model publishing no efforts
    is listed by :func:`unplaceable_models` instead.
    """
    return [_model_row(r) for r in _unplaced(levels, records) if r.reasoning_efforts]


def unplaceable_models(levels, records):
    """Current unplaced models that publish no efforts, so no row can name them."""
    return [
        _model_row(r) for r in _unplaced(levels, records) if not r.reasoning_efforts
    ]


def _level(document, name, field):
    for level in document:
        if level["name"] == name:
            return level
    raise LevelsError(
        "level_change_level_missing",
        "Name a level from yoke settings get levels.",
        field=field,
    )


def _find(document, selector, field):
    wanted = _selector(selector)
    for level in document:
        for index, entry in enumerate(level["options"]):
            if _selector(entry) == wanted:
                return level, index
    raise LevelsError(
        "level_change_option_missing",
        "Address a model/min_effort row exactly as levels get lists it.",
        field=field,
    )


def apply_level_changes(levels, changes):
    document = [level.payload() for level in levels]
    for index, change in enumerate(changes):
        field = f"changes[{index}]"
        kind = change.get("kind") if isinstance(change, dict) else None
        if kind not in CHANGE_KINDS:
            raise LevelsError(
                "level_change_kind_invalid",
                "Choose add, move, retire or change.",
                field=field,
            )
        if kind == "add":
            target = _level(document, change.get("level"), field)
            position = change.get("position", len(target["options"]))
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or not 0 <= position <= len(target["options"])
            ):
                raise LevelsError(
                    "level_change_position_invalid",
                    "Use a valid zero-based insertion position.",
                    field=field,
                )
            target["options"].insert(
                position, copy.deepcopy(change.get("option") or {})
            )
            continue
        level, position = _find(document, change.get("option") or {}, field)
        if kind == "retire":
            level["options"].pop(position)
        elif kind == "move":
            _level(document, change.get("to_level"), field)["options"].append(
                level["options"].pop(position)
            )
        else:
            level["options"][position]["min_effort"] = change.get("min_effort")
    return parse_levels(document)


__all__ = [
    "CHANGE_KINDS",
    "apply_level_changes",
    "generate_level_changes",
    "published_capability_conflicts",
    "refuse_capability_conflicts",
    "unplaceable_models",
    "unplaced_models",
]
