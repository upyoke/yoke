"""Local observations and serving-contract refusals use real boundary shapes."""

import json
import pytest
from uuid import uuid4

from yoke_cli.config.onboard_setup_facts import collect
from yoke_cli.commands.adapters import onboard_checklist_get as read_adapter
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.machine_config import reader as machine_config


def test_missing_identity_stays_unchecked(tmp_path):
    assert collect(config_path=tmp_path / "missing.json", checkout_path=tmp_path) == {
        "machine_id": None, "observations": {},
    }


def test_configuration_changes_are_rechecked_without_exposing_credentials(tmp_path):
    config = tmp_path / "config.json"
    identity = str(uuid4())
    payload = {
        "machine_id": identity, "active_env": "prod",
        "connections": {"prod": {"transport": "https", "api_url": "https://example.invalid",
                                  "credential_source": {"kind": "token_file", "path": str(tmp_path / "token")}}},
    }
    config.write_text(json.dumps(payload))
    first = collect(config_path=config, checkout_path=tmp_path)
    assert first["machine_id"] == identity
    assert first["observations"]["yoke-connection"]["status"] == "configured"
    assert "credential_source" not in json.dumps(first)
    payload["connections"] = {}
    config.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="setup_machine_config_unreadable"):
        collect(config_path=config, checkout_path=tmp_path)


def test_old_schema_refuses_without_sending_a_mutation(monkeypatch):
    calls = []
    monkeypatch.setattr(read_adapter, "ensure_handlers_loaded", lambda: None)
    def dispatch(**kwargs):
        calls.append(kwargs)
        return FunctionCallResponse(version="v1", success=True, function=kwargs["function_id"], result={"schema_version": 1})
    monkeypatch.setattr(read_adapter, "call_dispatcher", dispatch)
    response = read_adapter.get_setup(
        {"project_id": 7, "row_status": {"strategy-setup": "verified"}},
        TargetRef(kind="global", project_id="7"),
    )
    assert response.success is False
    assert response.error.code == "setup_facts_unavailable"
    assert [call["function_id"] for call in calls] == ["onboard.checklist.get"]
    assert "row_status" not in calls[0]["payload"]


@pytest.mark.parametrize("home_override", [False, True])
def test_selected_config_routes_get_and_restores_default_after_refusal(tmp_path, monkeypatch, home_override):
    default, selected = tmp_path / "default.json", tmp_path / "selected.json"
    selected.write_text(json.dumps({
        "machine_id": str(uuid4()), "active_env": "prod",
        "connections": {"prod": {"transport": "https", "api_url": "https://selected.invalid",
                                  "credential_source": {"kind": "token_file", "path": str(tmp_path / "token")}}},
    }))
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(default))
    if home_override:
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
        default = tmp_path / "machine-home" / "config.json"
    else:
        monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    monkeypatch.setattr(read_adapter, "ensure_handlers_loaded", lambda: None)
    calls = []
    def dispatch(**kwargs):
        calls.append(machine_config.active_connection()["api_url"])
        assert machine_config.config_path() == selected
        return FunctionCallResponse(version="v1", success=False, function=kwargs["function_id"],
                                    error=FunctionError(code="fixture_refused", message="No mutation."))
    monkeypatch.setattr(read_adapter, "call_dispatcher", dispatch)
    assert read_adapter.onboard_checklist_get(["--config", str(selected), "--project", "7", "--json"]) == 1
    assert calls == ["https://selected.invalid"]
    assert machine_config.config_path() == default
