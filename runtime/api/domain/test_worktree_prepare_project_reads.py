"""Prepare-child project reads work without a caller-local control database."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import db_helpers, worktree_provision as provision
from yoke_core.domain import worktree_validation_surface as surfaces
from runtime.api.domain.worktree_validation_surface_test_support import _webapp_sqlite_settings


@pytest.fixture(autouse=True)
def forbid_control_database(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("unmarked caller-local connection")

    monkeypatch.setattr(db_helpers, "connect", refuse)
    monkeypatch.setattr(surfaces, "connect", refuse, raising=False)
    monkeypatch.setattr(provision, "_run", refuse)


def install_relay(monkeypatch, result=None, error=None, crash=None):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if crash:
            raise crash
        return FunctionCallResponse(
            success=error is None, function=kwargs["function_id"], version="v1",
            result=result, error=error,
        )

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", dispatch,
    )
    return calls


def test_project_field_relays_without_subprocess_or_database(monkeypatch):
    calls = install_relay(monkeypatch, {"value": "trunk"})
    assert provision.project_field("sample", "default_branch", "/unused") == "trunk"
    assert calls[0]["function_id"] == "projects.get"
    assert calls[0]["payload"] == {"project": "sample", "field": "default_branch"}
    assert calls[0]["target"].kind == "global"


@pytest.mark.parametrize("operation", ["provision", "paths", "bindings"])
def test_validation_reads_relay_and_honor_declared_surface(monkeypatch, tmp_path, operation):
    calls = install_relay(monkeypatch, {"settings_json": json.dumps(_webapp_sqlite_settings())})
    if operation == "provision":
        result = surfaces.provision_validation_surfaces(tmp_path, "sample")
        assert result.surfaces[0].created
        assert result.surfaces[0].path.is_file()
    elif operation == "paths":
        assert surfaces.resolve_validation_db_paths(tmp_path, "sample")["primary"]["env_var"] == "APP_DB_PATH"
    else:
        assert surfaces.prompt_env_var_bindings(
            tmp_path, "sample", canonical_db_path="connected",
        )[1] == ("APP_DB_PATH", str(tmp_path / ".yoke/validation.db"))
    assert calls[0]["function_id"] == "projects.capability_settings.get"
    assert calls[0]["payload"] == {"project": "sample", "cap_type": "migration_model"}


def test_undeclared_capability_is_empty(monkeypatch, tmp_path):
    install_relay(monkeypatch, {"settings_json": None})
    assert surfaces.provision_validation_surfaces(tmp_path, "sample").surfaces == []


@pytest.mark.parametrize("reader,reason", [
    (lambda: provision.project_field("sample", "default_branch", "/unused"), "project_field_read_failed"),
    (lambda: surfaces.resolve_validation_db_paths("/lane", "sample"), "validation_capability_read_failed"),
])
@pytest.mark.parametrize("failure", ["refusal", "crash"])
def test_read_failure_names_reason_and_recovery(monkeypatch, reader, reason, failure):
    install_relay(
        monkeypatch,
        error=FunctionError(code="unavailable", message="control plane unavailable") if failure == "refusal" else None,
        crash=RuntimeError("transport unavailable") if failure == "crash" else None,
    )
    with pytest.raises(RuntimeError, match=reason) as raised:
        reader()
    assert "Recovery:" in str(raised.value)


def test_invalid_capability_is_reported(monkeypatch, tmp_path):
    install_relay(monkeypatch, {"settings_json": "{"})
    with pytest.raises(RuntimeError, match="validation_capability_invalid.*Recovery:"):
        surfaces.provision_validation_surfaces(tmp_path, "sample")


@pytest.mark.parametrize("value", [17, "17"])
def test_checkout_project_identity_relays(monkeypatch, value):
    from yoke_core.domain.project_checkout_locations import project_id_for_slug

    calls = install_relay(monkeypatch, {"value": value})
    assert project_id_for_slug("sample") == 17
    assert calls[0]["function_id"] == "projects.get"
    assert calls[0]["payload"] == {"project": "sample", "field": "id"}


@pytest.mark.parametrize("value", [None, "", "invalid", 0])
def test_checkout_invalid_identity_is_diagnosed(monkeypatch, value):
    from yoke_core.domain.project_checkout_locations import project_id_for_slug

    install_relay(monkeypatch, {"value": value})
    with pytest.raises(RuntimeError, match="project_checkout_identity_unavailable.*Recovery:"):
        project_id_for_slug("sample")


@pytest.mark.parametrize("failure", ["refusal", "crash"])
def test_checkout_failed_identity_is_diagnosed(monkeypatch, failure):
    from yoke_core.domain.project_checkout_locations import project_id_for_slug

    install_relay(
        monkeypatch,
        error=FunctionError(code="unavailable", message="identity unavailable") if failure == "refusal" else None,
        crash=RuntimeError("transport unavailable") if failure == "crash" else None,
    )
    with pytest.raises(RuntimeError, match="project_checkout_identity_unavailable.*Recovery:"):
        project_id_for_slug("sample")


def test_authority_detection_failure_does_not_choose_local(monkeypatch):
    from yoke_cli.config import machine_config
    from yoke_core.domain.worktree_create_db import item_worktree_authority_is_https

    def fail():
        raise RuntimeError("connection configuration unreadable")

    monkeypatch.setattr(machine_config, "active_connection", fail)
    with pytest.raises(RuntimeError, match="worktree_authority_unavailable.*Recovery:"):
        item_worktree_authority_is_https()


@pytest.mark.parametrize("failure", ["refusal", "crash"])
def test_provisioning_project_preserves_item_read_failure(monkeypatch, failure):
    from yoke_core.domain import worktree_create_db as creation

    monkeypatch.setattr(creation, "item_worktree_authority_is_https", lambda: True)
    install_relay(
        monkeypatch,
        error=FunctionError(code="unavailable", message="item read unavailable") if failure == "refusal" else None,
        crash=RuntimeError("transport unavailable") if failure == "crash" else None,
    )
    project, error = creation.provisioning_project("YOK-1", None, None)
    assert project == ""
    assert "provisioning_project_read_failed" in error
    assert "Recovery:" in error
    assert "unavailable" in error


@pytest.mark.parametrize("reader", ["string", "integer"])
def test_policy_reads_relay_without_local_database(monkeypatch, reader):
    from yoke_core.domain import project_settings

    calls = install_relay(monkeypatch, {"settings_json": '{"base_branch":"trunk","wip_cap":8}'})
    if reader == "string":
        assert project_settings.get_project_str_for_id(17, "base_branch") == "trunk"
    else:
        assert project_settings.get_project_int_for_id(17, "wip_cap") == 8
    assert calls[0]["function_id"] == "projects.capability_settings.get"
    assert calls[0]["payload"] == {"project": "17", "cap_type": "project-policy"}


@pytest.mark.parametrize("failure", ["refusal", "crash", "invalid"])
def test_policy_read_failure_is_diagnosed(monkeypatch, failure):
    from yoke_core.domain import project_settings

    install_relay(
        monkeypatch, {"settings_json": "[]"},
        error=FunctionError(code="unavailable", message="policy unavailable") if failure == "refusal" else None,
        crash=RuntimeError("transport unavailable") if failure == "crash" else None,
    )
    with pytest.raises(RuntimeError, match="project_policy_(read_failed|invalid).*Recovery:"):
        project_settings.get_project_str_for_id(17, "base_branch")


def test_policy_mapping_failure_is_diagnosed(monkeypatch):
    from yoke_core.domain import machine_config, project_settings

    def fail(*_args):
        raise RuntimeError("mapping unreadable")

    monkeypatch.setattr(machine_config, "project_id", fail)
    with pytest.raises(RuntimeError, match="project_policy_mapping_unavailable.*Recovery:"):
        project_settings.get_project_str("/lane", "base_branch")


def test_provisioning_project_relays_item_identity(monkeypatch):
    from yoke_core.domain import worktree_create_db as creation

    monkeypatch.setattr(creation, "item_worktree_authority_is_https", lambda: True)
    calls = install_relay(monkeypatch, {"item": {"project": {"slug": "sample"}}})
    assert creation.provisioning_project("YOK-1", None, None) == ("sample", "")
    assert calls[0]["function_id"] == "items.detail.get"


def test_absent_policy_retains_documented_default(monkeypatch):
    from yoke_core.domain import project_settings

    install_relay(monkeypatch, {"settings_json": None})
    assert project_settings.get_project_str_for_id(17, "base_branch") == "main"
