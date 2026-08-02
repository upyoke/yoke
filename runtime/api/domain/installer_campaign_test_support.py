"""Shared assertions for the current installer campaign catalog tests."""

from __future__ import annotations

from collections.abc import Mapping


def contains_key(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        return key in value or any(contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(contains_key(child, key) for child in value)
    return False


def terminal_configs(
    case: Mapping[str, object],
) -> list[Mapping[str, object]]:
    config = case["method_config"]
    assert isinstance(config, Mapping)
    variants = config.get("baseline_configs")
    if isinstance(variants, Mapping):
        return [
            variant for variant in variants.values() if isinstance(variant, Mapping)
        ]
    return [config]


def selection_keys(rows: list[object], value: str) -> tuple[str, ...]:
    index = next(
        index for index, row in enumerate(rows) if getattr(row, "value", None) == value
    )
    return ("Down",) * index + ("Enter",)


def action_signature(
    config: Mapping[str, object],
) -> list[tuple[str, tuple[str, ...]]]:
    actions = config["actions"]
    assert isinstance(actions, list)
    return [
        (
            str(action["step"]),
            tuple(str(key) for key in action.get("keys", [])),
        )
        for action in actions
        if isinstance(action, Mapping)
    ]


def action_window(
    config: Mapping[str, object],
    *,
    first: str,
    last: str,
) -> list[tuple[str, tuple[str, ...]]]:
    signature = action_signature(config)
    start = next(
        index for index, (step, _keys) in enumerate(signature) if step == first
    )
    end = next(
        index
        for index, (step, _keys) in enumerate(signature[start:], start=start)
        if step == last
    )
    return signature[start : end + 1]
