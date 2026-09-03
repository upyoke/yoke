"""Cross-release machine-config compatibility for launch preferences."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_cli.config import machine_config_mutation
from yoke_contracts.machine_config import schema as machine_config_contract
from yoke_contracts.machine_config.preferred_session_models import (
    PREFERRED_SESSION_MODELS_KEY,
    PREFERRED_SESSION_REASONING_EFFORTS_KEY,
    resolve_launch_selection,
    validate_preferred_session_models,
)


def _previous_preference_contract_issues(
    payload: Mapping[str, Any],
) -> list[str]:
    """Model-map checks shipped immediately before the additive effort map."""
    raw = payload.get(PREFERRED_SESSION_MODELS_KEY)
    if not isinstance(raw, Mapping):
        return ["preferred_session_models must be an object"]
    issues = []
    for surface, value in raw.items():
        if not str(surface).strip():
            issues.append("surface must be non-empty")
        if not isinstance(value, str):
            issues.append(f"{surface} must be a string model id")
    return issues


def test_new_writer_document_loads_under_previous_preference_contract(
    tmp_path,
) -> None:
    config = tmp_path / "config.json"
    payload = machine_config_contract.canonical_example_payload()

    machine_config_mutation.write_payload(payload, config)
    written = json.loads(config.read_text(encoding="utf-8"))

    assert _previous_preference_contract_issues(written) == []
    assert all(
        isinstance(value, str)
        for value in written[PREFERRED_SESSION_MODELS_KEY].values()
    )
    assert PREFERRED_SESSION_REASONING_EFFORTS_KEY in written


def test_previous_shared_document_loads_without_rewrite() -> None:
    payload = {
        PREFERRED_SESSION_MODELS_KEY: {
            "claude-cli": "claude-opus-5[1m]",
            "codex-cli": "gpt-5.6-sol",
            "cursor-cli": "claude-opus-5-thinking-high",
            "codex-desktop": "",
        }
    }

    resolved = resolve_launch_selection(None, None, None, "claude-cli", payload=payload)

    assert validate_preferred_session_models(payload) == []
    assert resolved.model == "claude-opus-5"
    assert resolved.context_window_tokens == 1_000_000
    assert payload[PREFERRED_SESSION_MODELS_KEY]["claude-cli"].endswith("[1m]")
