"""Machine-config launch-default keys are retired: warned, stripped, ignored."""

from __future__ import annotations

import dataclasses
import json

import pytest

from yoke_cli.config import machine_config_mutation
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config.retired_keys import (
    RETIRED_MACHINE_CONFIG_KEYS,
    retired_key_issues,
    strip_retired_keys,
)
from yoke_contracts.session_control.relay_models import RelayClaimRequest
from yoke_core.domain.session_relay_types import RelayHeartbeat


RETIRED = (
    "preferred_session_models",
    "preferred_session_reasoning_efforts",
    "session_model_routing",
)


def _with_retired_keys(payload: dict) -> dict:
    payload["preferred_session_models"] = {"claude-cli": "claude-opus-5[1m]"}
    payload["preferred_session_reasoning_efforts"] = {"claude-cli": "max"}
    payload["session_model_routing"] = {"tier1": ["claude-cli"]}
    return payload


def test_the_retired_set_is_exactly_the_three_launch_default_keys() -> None:
    assert set(RETIRED_MACHINE_CONFIG_KEYS) == set(RETIRED)


def test_validation_warns_once_per_retired_key_without_refusing() -> None:
    payload = _with_retired_keys(contract.canonical_example_payload())

    issues = [
        issue
        for issue in contract.validate_payload(payload)
        if issue.code == "machine_config_key_retired"
    ]

    assert sorted(issue.path for issue in issues) == sorted(RETIRED)
    assert {issue.severity for issue in issues} == {"warning"}
    assert all("--level" in issue.message for issue in issues)
    assert all(issue.hint for issue in issues)


def test_a_config_without_retired_keys_draws_no_retirement_warning() -> None:
    assert retired_key_issues(contract.canonical_example_payload()) == []
    assert not any(
        issue.code == "machine_config_key_retired"
        for issue in contract.validate_payload(contract.canonical_example_payload())
    )


def test_the_canonical_example_carries_no_retired_key() -> None:
    assert not set(RETIRED) & set(contract.canonical_example_payload())


def test_strip_removes_only_retired_keys_and_names_them() -> None:
    payload = _with_retired_keys({"schema_version": 1, "settings": {}})

    removed = strip_retired_keys(payload)

    assert set(removed) == set(RETIRED)
    assert payload == {"schema_version": 1, "settings": {}}
    assert strip_retired_keys(payload) == ()


def test_a_config_write_drops_every_retired_key(tmp_path) -> None:
    config = tmp_path / "config.json"
    payload = _with_retired_keys(contract.canonical_example_payload())

    machine_config_mutation.write_payload(payload, config)

    written = json.loads(config.read_text(encoding="utf-8"))
    assert not set(RETIRED) & set(written)
    assert written["schema_version"] == contract.SCHEMA_VERSION


def test_a_fresh_config_load_seeds_no_launch_defaults(tmp_path) -> None:
    payload, _path = machine_config_mutation.load_payload(tmp_path / "config.json")

    assert payload == {"schema_version": contract.SCHEMA_VERSION}


def test_a_relay_claim_from_an_older_relay_still_validates() -> None:
    """Older relays still send both maps; refusing them would drop the poll."""
    request = RelayClaimRequest.model_validate(
        {
            "relay_id": "relay-1",
            "machine_id": "machine-1",
            "hostname": "relay-host",
            "relay_version": "0.1.0",
            "projects": [10],
            "surfaces": {"claude-cli": "2.1.259"},
            "preferred_models": {"claude-cli": "claude-opus-5[1m]"},
            "preferred_reasoning_efforts": {"claude-cli": "max"},
        }
    )

    assert request.preferred_models == {"claude-cli": "claude-opus-5[1m]"}


def test_a_relay_claim_without_the_retired_maps_validates() -> None:
    request = RelayClaimRequest.model_validate(
        {
            "relay_id": "relay-1",
            "machine_id": "machine-1",
            "hostname": "relay-host",
            "relay_version": "0.1.0",
            "projects": [10],
            "surfaces": {},
        }
    )

    assert request.preferred_models == {}
    assert request.preferred_reasoning_efforts == {}


@pytest.mark.parametrize(
    "field", ["preferred_session_models", "preferred_session_reasoning_efforts"]
)
def test_the_server_heartbeat_carries_no_launch_defaults(field: str) -> None:
    assert field not in {item.name for item in dataclasses.fields(RelayHeartbeat)}
