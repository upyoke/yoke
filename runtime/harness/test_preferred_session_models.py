"""Preferred-model map resolution and machine-config validation."""

from __future__ import annotations

from yoke_contracts.machine_config.preferred_session_models import (
    EXPLICIT_SOURCE,
    PREFERRED_SESSION_MODELS_KEY,
    VENDOR_DEFAULT_SOURCE,
    list_preferred_models,
    render_list_models,
    resolve_launch_model,
    validate_preferred_session_models,
)
from yoke_contracts.machine_config import schema as contract


def test_explicit_model_outranks_preferred_map() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}}

    resolved = resolve_launch_model("explicit-model", "cursor-cli", payload=payload)

    assert resolved.model == "explicit-model"
    assert resolved.source == EXPLICIT_SOURCE


def test_preferred_map_outranks_vendor_default() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}}

    resolved = resolve_launch_model(None, "cursor-cli", payload=payload)

    assert resolved.model == "preferred-model"
    assert resolved.source == f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli"


def test_missing_surface_falls_through_to_vendor_default() -> None:
    payload = {PREFERRED_SESSION_MODELS_KEY: {"claude-cli": "claude-opus"}}

    resolved = resolve_launch_model("", "cursor-cli", payload=payload)

    assert resolved.model is None
    assert resolved.source == VENDOR_DEFAULT_SOURCE


def test_invalid_map_is_rejected_by_machine_config() -> None:
    payload = contract.canonical_example_payload()
    payload[PREFERRED_SESSION_MODELS_KEY] = {"cursor-cli": ""}

    issues = validate_preferred_session_models(payload)
    full = contract.validate_payload(payload)

    assert any(
        issue.code == "preferred_session_models_model_invalid" for issue in issues
    )
    assert any(issue.code == "preferred_session_models_model_invalid" for issue in full)


def test_canonical_example_preferred_map_is_valid() -> None:
    payload = contract.canonical_example_payload()

    assert payload[PREFERRED_SESSION_MODELS_KEY]["cursor-cli"]
    assert contract.validate_payload(payload) == []


def test_list_models_names_the_config_key_as_source(monkeypatch, tmp_path) -> None:
    config = tmp_path / "config.json"
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}
        },
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: config,
    )

    report = list_preferred_models("cursor-cli")
    rendered = render_list_models(report, json_mode=False)

    assert report["key"] == PREFERRED_SESSION_MODELS_KEY
    assert report["selected"]["source"] == f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli"
    assert "preferred-model" in rendered
    assert f"{PREFERRED_SESSION_MODELS_KEY}.cursor-cli" in rendered
