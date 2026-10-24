"""Validate a ``project-policy`` settings document before it is stored.

Routed from ``projects_capability_settings_validation.canonicalize_capability_settings``
for both the full-document set and the merge path, so a save and a merge
reject the same out-of-range value the same way and the previously stored
document is left untouched on rejection.
"""

from __future__ import annotations

from yoke_contracts.project_contract.disposable_generated_paths_policy import (
    disposable_generated_paths_setting_error,
)
from yoke_contracts.project_contract.project_keys import (
    DB_PROJECT_POLICY_KEYS,
    RECOGNIZED_PROJECT_KEYS,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.settings_catalog import resolve_setting
from yoke_contracts.title_policy import title_max_length_setting_error

from yoke_core.domain import json_helper


def validate_json_string(raw_json: str) -> str:
    """Validate and canonicalize a ``project-policy`` settings document."""
    payload = json_helper.loads_text(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("project-policy settings must be a JSON object")
    for key, value in payload.items():
        if key == "board":  # Structured board preferences retain their own owner.
            continue
        if key not in DB_PROJECT_POLICY_KEYS:
            resolve_setting(key)  # supplies the closest-key recovery for unknown keys
            raise ValueError(
                compose_refusal(
                    f"setting_scope_invalid: {key} is not project policy.",
                    recovery="yoke settings list --scope project",
                )
            )
        RECOGNIZED_PROJECT_KEYS[key].validate(key, value)
    if "title_max_length" in payload:
        error = title_max_length_setting_error(payload["title_max_length"])
        if error:
            raise ValueError(error)
    if "disposable_generated_paths" in payload:
        error = disposable_generated_paths_setting_error(
            payload["disposable_generated_paths"]
        )
        if error:
            raise ValueError(error)
    return json_helper.dumps_compact(payload)


__all__ = ["validate_json_string"]
