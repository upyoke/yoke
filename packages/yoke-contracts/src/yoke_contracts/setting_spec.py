"""Typed, non-sensitive setting contract shared by every scope."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
from typing import Any


@dataclass(frozen=True)
class SettingSpec:
    default: Any
    value_type: type
    meaning: str
    minimum: int | None = None
    allowed_values: tuple[Any, ...] | None = None
    fields: tuple[str, ...] | None = None

    def validate(self, key: str, value: Any) -> Any:
        if type(value) is not self.value_type:
            raise ValueError(
                f"setting_value_invalid: {key} must be { {int: 'integer', list: 'JSON array'}.get(self.value_type, self.value_type.__name__) }. Recovery: yoke settings list"
            )
        if self.fields is not None:
            if set(value) != set(self.fields) or not all(
                isinstance(v, str) for v in value.values()
            ):
                raise ValueError(
                    f"setting_value_invalid: {key} requires only {self.fields} string fields. Recovery: yoke settings unset {key}"
                )
        if self.minimum is not None and value < self.minimum:
            raise ValueError(
                f"setting_value_invalid: {key} must be at least {self.minimum}. Recovery: yoke settings list"
            )
        if self.allowed_values is not None and value not in self.allowed_values:
            raise ValueError(
                f"setting_value_invalid: {key} must be one of {self.allowed_values}. Recovery: yoke settings list"
            )
        return copy.deepcopy(value)

    def parse(self, key: str, text: str) -> Any:
        if self.value_type is str:
            value = text
        else:
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise ValueError(
                    f"setting_value_invalid: {key} requires JSON {self.value_type.__name__}. Recovery: yoke settings list"
                ) from exc
        return self.validate(key, value)

    def stored_value(self, key: str, value: Any) -> Any:
        # Machine config has always persisted scalar strings as well as JSON.
        if isinstance(value, str) and self.value_type in (int, bool):
            return self.parse(key, value)
        return self.validate(key, value)
