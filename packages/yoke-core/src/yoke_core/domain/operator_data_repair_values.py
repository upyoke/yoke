"""Secret-key screening for operator data repair snapshots.

Repair evidence must never carry secret-bearing values, so snapshot values
are made JSON-safe with any secret-named column or JSON key redacted. A
redacted value then differs from its source, which the repair refuses.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.handlers.db_read import json_safe


_SENSITIVE_KEY_TOKENS = (
    "credential",
    "dsn",
    "encryptedkey",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "token",
)


def is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def redacted_json_safe(value: Any, *, column_name: str = "") -> Any:
    if is_sensitive_key(column_name):
        return "<redacted>" if value is not None else None
    if isinstance(value, str):
        return _redact_json_text(value)
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if is_sensitive_key(str(key)) and item is not None
                else redacted_json_safe(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redacted_json_safe(item) for item in value]
    return json_safe(value)


def _redact_json_text(value: str) -> str:
    stripped = value.lstrip()
    if not stripped.startswith(("{", "[")):
        return value
    try:
        decoded = json_helper.loads_text(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(decoded, (dict, list)):
        return value
    return json_helper.dumps_compact(redacted_json_safe(decoded))
