"""Unified settings preserve scope authority and reject unsafe writes."""

import io
import json

import pytest

from yoke_cli.commands.adapters import settings
from yoke_cli.commands.adapters.settings_store import SettingsStore
from yoke_cli.config import machine_config
from yoke_cli.config.runtime_settings_write import write_setting
from yoke_contracts.setting_spec import SettingSpec
from yoke_contracts.settings_catalog import (
    CATALOG,
    SCOPES,
    build_catalog,
    resolve_setting,
)
from yoke_contracts.organization_contract.fleet_keys import (
    merge_fleet_settings,
    get_fleet_setting,
)
from yoke_core.domain import runtime_settings
from yoke_core.domain.project_policy_settings_write import validate_json_string


@pytest.fixture
def local_config(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "config.json"


def test_catalog_unique_typed_and_secret_free():
    assert len(CATALOG) == sum(len(keys) for keys in SCOPES.values())
    for key, (_, spec) in CATALOG.items():
        spec.validate(key, spec.default)
        assert spec.meaning
    with pytest.raises(ValueError, match="setting_key_duplicate"):
        build_catalog(
            {
                "machine": {"x": SettingSpec(1, int, "x")},
                "project": {"x": SettingSpec(1, int, "x")},
            }
        )
    for key in (
        "api_key",
        "access_token",
        "password",
        "credential_file",
        "private_key",
    ):
        with pytest.raises(ValueError, match="setting_key_sensitive"):
            build_catalog({"machine": {key: SettingSpec("", str, "bad")}})


def test_machine_round_trip_local_only(local_config, monkeypatch):
    monkeypatch.setattr(
        SettingsStore, "call", lambda *a: pytest.fail("local setting relayed")
    )
    assert settings.set_value(["max_active_worktrees", "12"]) == 0
    assert machine_config.load_config()["settings"]["max_active_worktrees"] == 12
    assert SettingsStore().read("max_active_worktrees")["source"] == "stored"
    assert settings.unset(["max_active_worktrees"]) == 0
    assert SettingsStore().read("max_active_worktrees")["source"] == "default"
    assert "max_active_worktrees" not in machine_config.load_config()["settings"]


def test_invalid_machine_write_preserves_document(local_config):
    write_setting("max_active_worktrees", 12)
    before = local_config.read_bytes()
    for invalid in (True, "many", -1):
        with pytest.raises(ValueError, match="setting_value_invalid"):
            write_setting("max_active_worktrees", invalid)
    with pytest.raises(ValueError, match="setting_key_unknown"):
        write_setting("access_token", "secret")
    assert local_config.read_bytes() == before


def test_typed_refusal_and_closest_key(local_config, capsys):
    assert settings.set_value(["max_active_worktrees", "many"]) == 2
    assert "setting_value_invalid" in capsys.readouterr().err
    with pytest.raises(ValueError, match="Did you mean max_active_worktrees"):
        resolve_setting("max_active_worktree")


def test_document_stdin(local_config, monkeypatch):
    monkeypatch.setattr(
        "sys.stdin", io.StringIO('{"origin":"https://example.com","channel":"stable"}')
    )
    assert settings.set_value(["distribution", "-"]) == 0
    assert (
        machine_config.load_config()["settings"]["distribution"]["channel"] == "stable"
    )
    with pytest.raises(ValueError):
        write_setting(
            "distribution",
            {"origin": "https://example.com", "channel": "stable", "token": "no"},
        )


@pytest.mark.parametrize(
    "key,value,function,payload",
    [
        (
            "wip_cap",
            8,
            "projects.capability_settings.merge",
            {
                "project": "example",
                "cap_type": "project-policy",
                "assignments": {"wip_cap": 8},
            },
        ),
        (
            "membership.auto_join_domain_verified",
            True,
            "organizations.settings.merge",
            {"assignments": {"membership.auto_join_domain_verified": True}},
        ),
        ("levels", [], "universe.levels.set", {"levels": []}),
        (
            "cursor_quota_order",
            ["Other Models", "Cursor Models"],
            "universe.cursor_quota_order.set",
            {"pools": ["Other Models", "Cursor Models"]},
        ),
    ],
)
def test_write_authority_routing(monkeypatch, key, value, function, payload):
    calls = []
    monkeypatch.setattr(
        SettingsStore, "call", lambda self, fn, data: calls.append((fn, data))
    )
    SettingsStore("example").write(key, value)
    assert calls == [(function, payload)]


def test_project_unset_uses_read_and_cas(monkeypatch):
    calls = []

    def call(self, fn, payload):
        calls.append((fn, payload))
        return {"settings_json": '{"wip_cap":8,"title_max_length":50}'}

    monkeypatch.setattr(SettingsStore, "call", call)
    SettingsStore("example").write("wip_cap", unset=True)
    assert calls[1][0] == "projects.capability_settings.set"
    assert json.loads(calls[1][1]["settings_json"]) == {"title_max_length": 50}
    assert json.loads(calls[1][1]["base_settings_json"])["wip_cap"] == 8


def test_org_and_levels_unset_keep_existing_writer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        SettingsStore, "call", lambda self, fn, data: calls.append((fn, data))
    )
    SettingsStore().write("membership.auto_join_domain_verified", unset=True)
    SettingsStore().write("levels", unset=True)
    assert calls == [
        (
            "organizations.settings.merge",
            {"assignments": {"membership.auto_join_domain_verified": None}},
        ),
        ("universe.levels.reset", {}),
    ]
    merged, _ = merge_fleet_settings(
        {"membership": {"auto_join_domain_verified": True}},
        {"membership.auto_join_domain_verified": None},
    )
    assert get_fleet_setting(merged, "membership.auto_join_domain_verified") == (
        False,
        True,
    )


def test_runtime_defaults_and_invalid_stored_value(local_config):
    assert (
        runtime_settings.get_int("max_active_worktrees", 999)
        == CATALOG["max_active_worktrees"][1].default
    )
    local_config.write_text('{"settings":{"max_active_worktrees":"many"}}')
    with pytest.raises(ValueError, match="setting_value_invalid"):
        runtime_settings.get_int("max_active_worktrees", 999)


def test_unknown_project_key_refuses_and_keeps_board_owner():
    with pytest.raises(ValueError, match="Did you mean wip_cap"):
        validate_json_string('{"wip_capp":5}')
    assert json.loads(validate_json_string('{"board":{},"wip_cap":5}'))["wip_cap"] == 5


def test_removed_commands_have_no_alias():
    from yoke_cli.commands.registry import (
        SUBCOMMAND_REGISTRY,
        SUBCOMMAND_ALIAS_REGISTRY,
    )

    for prefix in (
        ("universe", "levels"),
        ("universe", "cursor-quota-order"),
        ("organizations", "settings"),
        ("machine", "settings"),
    ):
        assert not any(
            route[: len(prefix)] == prefix
            for route in {*SUBCOMMAND_REGISTRY, *SUBCOMMAND_ALIAS_REGISTRY}
        )
    assert ("machine", "access", "get") in SUBCOMMAND_REGISTRY


def test_quota_unset_removes_override_and_reads_shipped_order(monkeypatch):
    import sqlite3
    from yoke_core.domain.quota_pool_order import (
        set_pool_order,
        read_pool_order,
        DEFAULT_CURSOR_QUOTA_ORDER,
    )

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE universe_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, updated_by_actor_id INTEGER)"
    )
    set_pool_order(conn, pools=["Other Models", "Cursor Models"], actor_id=7)
    assert read_pool_order(conn) == ("Other Models", "Cursor Models")
    calls = []
    monkeypatch.setattr(
        SettingsStore, "call", lambda self, fn, payload: calls.append((fn, payload))
    )
    SettingsStore().write("cursor_quota_order", unset=True)
    assert calls == [("universe.cursor_quota_order.set", {"pools": None})]
    set_pool_order(conn, pools=None, actor_id=7)
    assert read_pool_order(conn) == DEFAULT_CURSOR_QUOTA_ORDER
    assert conn.execute("SELECT COUNT(*) FROM universe_settings").fetchone()[0] == 0


def test_authority_refusal_is_not_reported_as_success(monkeypatch):
    from yoke_cli.commands.adapters import settings_store
    from yoke_cli.commands.adapters.settings_store import SettingsCallError
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    monkeypatch.setattr(settings_store, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(settings_store, "build_actor", lambda **kw: object())
    response = FunctionCallResponse(
        success=False,
        function="organizations.settings.merge",
        version="v1",
        request_id="test",
        error=FunctionError(
            code="org_admin_required", message="An org admin must change this setting"
        ),
    )
    monkeypatch.setattr(settings_store, "call_dispatcher", lambda **kw: response)
    with pytest.raises(SettingsCallError) as caught:
        SettingsStore().write("membership.auto_join_domain_verified", True)
    assert caught.value.response.error.code == "org_admin_required"


def test_stored_distribution_cannot_print_extra_secret_fields(local_config, capsys):
    local_config.write_text(
        '{"settings":{"distribution":{"origin":"https://example.com","channel":"stable","token":"private"}}}'
    )
    assert settings.get(["distribution"]) == 2
    assert "private" not in capsys.readouterr().err
