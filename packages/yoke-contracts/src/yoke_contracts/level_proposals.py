"""Model refresh proposes level changes; the operator approves them.

A proposal is an ordered list of changes against the current levels
document. Four kinds exist: ``add`` an option to a level (at ``position``
when given, else last), ``move`` an option to the end of ``to_level``, ``retire`` an option, and ``change`` an option's reasoning
effort or context window. Options are addressed by surface, model, and
effort — the same triple that labels a session.

:func:`generate_level_changes` extrapolates the mechanical part from the
catalog: an option whose model the catalog marks superseded is replaced in
place by its successor, and an option whose effort or context the model's
provider does not publish is moved to the nearest published effort, or to
the model's default context window. A model
no option launches is reported as unplaced, never placed by guesswork; the
refresh author adds it with an explicit ``add`` change.

:func:`published_capability_conflicts` checks options against each model's
published reasoning efforts and context windows. Nothing here writes: the
approved document is stored by ``yoke universe levels set``.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Optional, Sequence

from yoke_contracts.levels import Level, LevelOption, LevelsError, parse_levels
from yoke_contracts.model_reference import lookup_model_reference, lookup_stem
from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.session_control.model_selection import SURFACE_EFFORT_LEVELS
from yoke_contracts.session_model_facts import REASONING_EFFORT_VALUES

CHANGE_KINDS: tuple[str, ...] = ("add", "move", "retire", "change")
_SELECTOR_KEYS = ("surface", "model", "reasoning_effort")


def _record(model: str, records: Sequence[ModelRecord]) -> Optional[ModelRecord]:
    return lookup_model_reference(model, records).record


def _selector(option: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(option.get(key) or "").strip() for key in _SELECTOR_KEYS}


def _nearest_effort(wanted: str, published: Sequence[str], surface: str) -> str:
    """The highest launchable published effort not above ``wanted``.

    Falls back to the lowest launchable one; with none, ``wanted`` stays and
    the conflict check names it.
    """
    order = {effort: rank for rank, effort in enumerate(REASONING_EFFORT_VALUES)}
    accepted = SURFACE_EFFORT_LEVELS.get(surface, ())
    ranked = sorted(
        (e for e in published if e in accepted), key=lambda e: order.get(e, -1)
    )
    if not ranked:
        return wanted
    below = [e for e in ranked if order.get(e, -1) <= order.get(wanted, -1)]
    return below[-1] if below else ranked[0]


def published_capability_conflicts(
    levels: Sequence[Level], records: Sequence[ModelRecord]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return options the provider contradicts, and options nothing verifies.

    A conflict names the field, the option's value, and the published values.
    An option is unverified when its model is not in the catalog or the
    catalog publishes neither efforts nor windows for it.
    """
    conflicts: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    for level in levels:
        for top in level.options:
            for option in (top, top.fallback):
                if option is None:
                    continue
                where = {"level": level.name, **_selector(option.payload())}
                record = _record(option.model, records)
                if record is None or not (
                    record.reasoning_efforts or record.context_window_tokens
                ):
                    reason = (
                        "model not in catalog"
                        if record is None
                        else ("catalog publishes no efforts or context windows")
                    )
                    unverified.append({**where, "reason": reason})
                    continue
                efforts = record.reasoning_efforts
                if efforts and option.reasoning_effort not in efforts:
                    conflicts.append(
                        {
                            **where,
                            "field": "reasoning_effort",
                            "value": option.reasoning_effort,
                            "published": list(efforts),
                            "model_id": record.model_id,
                        }
                    )
                windows = record.context_window_tokens
                context = option.context_window_tokens
                if windows and context is not None and context not in windows:
                    conflicts.append(
                        {
                            **where,
                            "field": "context_window_tokens",
                            "value": context,
                            "published": list(windows),
                            "model_id": record.model_id,
                        }
                    )
    return conflicts, unverified


def refuse_capability_conflicts(conflicts: Sequence[Mapping[str, Any]]) -> None:
    """Raise the first conflict as a named refusal with its recovery."""
    if not conflicts:
        return
    first = conflicts[0]
    raise LevelsError(
        f"level_option_{first['field']}_unpublished",
        f"{first['surface']} {first['model']} at level {first['level']} names "
        f"{first['field']} {first['value']!r}, but {first['model_id']} publishes "
        f"{', '.join(str(v) for v in first['published'])}"
        + (f" ({len(conflicts)} conflicts in total)" if len(conflicts) > 1 else "")
        + ". Recovery: run `yoke models level-proposal` for the corrected "
        "levels, or correct the model's published values with `yoke models "
        "publish`.",
        field=f"{first['level']}.{first['field']}",
    )


def _successor_model(option: LevelOption, old: ModelRecord, new: ModelRecord) -> str:
    """Carry the option's selector shape from the old model to its successor."""
    stem = lookup_stem(option.model)
    suffix = option.model[len(stem) :]
    old_keys = (old.model_id, *old.aliases)
    new_keys = (new.model_id, *new.aliases)
    index = next(
        (i for i, key in enumerate(old_keys) if stem in (key, lookup_stem(key))), 0
    )
    base = new_keys[index] if index < len(new_keys) else new.model_id
    return lookup_stem(base) + suffix


def _revised(
    selection: LevelOption, records: Sequence[ModelRecord]
) -> Optional[tuple[dict[str, Any], str]]:
    """Return one selection carried to its successor or published values."""
    record = _record(selection.model, records)
    if record is None:
        return None
    by_id = {r.model_id: r for r in records}
    successor = by_id.get(record.replacement_model_id or "")
    target = successor if successor and successor is not record else record
    model = selection.model
    if target is not record:
        model = _successor_model(selection, record, target)
    effort = selection.reasoning_effort
    if target.reasoning_efforts and effort not in target.reasoning_efforts:
        effort = _nearest_effort(effort, target.reasoning_efforts, selection.surface)
        old_suffix = f"-{selection.reasoning_effort}"
        if model.endswith(old_suffix):
            model = model[: -len(old_suffix)] + f"-{effort}"
    context = selection.context_window_tokens
    windows = target.context_window_tokens
    if windows and context is not None and context not in windows:
        context = None  # the model's default window always launches
    revised = {
        "surface": selection.surface,
        "model": model,
        "reasoning_effort": effort,
        "context_window_tokens": context,
    }
    current = {k: v for k, v in selection.payload().items() if k != "fallback"}
    if revised == current:
        return None
    if target is not record:
        return (
            revised,
            f"{record.model_id} is superseded by {target.model_id} in the catalog",
        )
    return (
        revised,
        f"{record.model_id} does not publish the option's effort or context window",
    )


def _option_changes(
    level: Level, option: LevelOption, records: Sequence[ModelRecord]
) -> list[dict[str, Any]]:
    top = _revised(option, records)
    fallback = None if option.fallback is None else _revised(option.fallback, records)
    if top is None and fallback is None:
        return []
    selector = _selector(option.payload())
    if fallback is None and top is not None and top[0]["model"] == option.model:
        revised, reason = top
        change = {
            key: revised[key]
            for key in ("reasoning_effort", "context_window_tokens")
            if revised[key] != getattr(option, key)
        }
        return [{"kind": "change", "option": selector, **change, "reason": reason}]
    added = (
        top[0]
        if top
        else {k: v for k, v in option.payload().items() if k != "fallback"}
    )
    if option.fallback is not None:
        added["fallback"] = fallback[0] if fallback else option.fallback.payload()
    reason = "; ".join(item[1] for item in (top, fallback) if item is not None)
    return [
        {"kind": "retire", "option": selector, "reason": reason},
        {
            "kind": "add",
            "level": level.name,
            "option": added,
            "position": level.options.index(option),
            "reason": reason,
        },
    ]


def unplaced_models(
    levels: Sequence[Level], records: Sequence[ModelRecord]
) -> list[dict[str, Any]]:
    """Catalog models no option launches and nothing supersedes."""
    placed: set[str] = set()
    for level in levels:
        for option in level.options:
            for selection in (option, option.fallback):
                if selection is not None and (r := _record(selection.model, records)):
                    placed.add(r.model_id)
    return [
        {"model_id": r.model_id, "provider": r.provider, "display_name": r.display_name}
        for r in records
        if r.model_id not in placed and not r.replacement_model_id
    ]


def generate_level_changes(
    levels: Sequence[Level], records: Sequence[ModelRecord]
) -> list[dict[str, Any]]:
    """Extrapolate the changes the catalog implies for these levels."""
    changes: list[dict[str, Any]] = []
    for level in levels:
        for option in level.options:
            changes.extend(_option_changes(level, option, records))
    return changes


def _find(document: list[dict[str, Any]], selector: Mapping[str, Any], field: str):
    wanted = _selector(selector)
    for level in document:
        for index, option in enumerate(level["options"]):
            if _selector(option) == wanted:
                return level, index
    raise LevelsError(
        "level_change_option_missing",
        f"no level holds {wanted['surface']} {wanted['model']} at "
        f"{wanted['reasoning_effort']} effort; address an option exactly as "
        "`yoke universe levels get --json` lists it.",
        field=f"{field}.option",
    )


def _level(document: list[dict[str, Any]], name: Any, field: str) -> dict[str, Any]:
    for level in document:
        if level["name"] == name:
            return level
    raise LevelsError(
        "level_change_level_missing",
        f"no level is named {name!r}; levels are "
        f"{', '.join(level['name'] for level in document)}.",
        field=field,
    )


def apply_level_changes(
    levels: Sequence[Level], changes: Iterable[Mapping[str, Any]]
) -> tuple[Level, ...]:
    """Apply changes in order and return the validated resulting levels."""
    document = [level.payload() for level in levels]
    for index, change in enumerate(changes):
        field = f"changes[{index}]"
        kind = change.get("kind") if isinstance(change, Mapping) else None
        if kind not in CHANGE_KINDS:
            raise LevelsError(
                "level_change_kind_invalid",
                f"kind must be one of {', '.join(CHANGE_KINDS)}.",
                field=f"{field}.kind",
            )
        if kind == "add":
            target = _level(document, change.get("level"), f"{field}.level")
            option = copy.deepcopy(dict(change.get("option") or {}))
            position = change.get("position", len(target["options"]))
            if isinstance(position, bool) or not isinstance(position, int):
                raise LevelsError(
                    "level_change_position_invalid",
                    "position is the option's zero-based index in its level.",
                    field=f"{field}.position",
                )
            target["options"].insert(position, option)
            continue
        level, position = _find(document, change.get("option") or {}, field)
        if kind == "retire":
            level["options"].pop(position)
        elif kind == "move":
            target = _level(document, change.get("to_level"), f"{field}.to_level")
            target["options"].append(level["options"].pop(position))
        else:
            option = level["options"][position]
            for key in ("reasoning_effort", "context_window_tokens"):
                if key in change:
                    option[key] = change[key]
    for level in document:
        if not level["options"]:
            raise LevelsError(
                "level_options_missing",
                f"the changes leave {level['name']} with no launchable option; "
                "add a replacement before retiring or moving its last one.",
                field="changes",
            )
    return parse_levels(document)


__all__ = [
    "CHANGE_KINDS",
    "apply_level_changes",
    "generate_level_changes",
    "published_capability_conflicts",
    "refuse_capability_conflicts",
    "unplaced_models",
]
