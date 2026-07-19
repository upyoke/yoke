"""Validated collection values shared by composed Pulumi stacks."""

import pulumi


def config_string_list(config, name: str) -> list[str]:
    values = config.get_object(name) or []
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise pulumi.RunError(f"{name} must be a JSON string array")
    return [value.strip() for value in values]


def config_string_map(config, name: str) -> dict[str, str]:
    values = config.get_object(name) or {}
    if not isinstance(values, dict) or any(
        not isinstance(key, str) or not key.strip()
        or not isinstance(value, str) or not value.strip()
        for key, value in values.items()
    ):
        raise pulumi.RunError(f"{name} must be a JSON string map")
    return {key.strip(): value.strip() for key, value in values.items()}


__all__ = ["config_string_list", "config_string_map"]
