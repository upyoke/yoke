"""`yoke machine` routes, payloads, and the registry usage rows."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import machine
from yoke_cli.commands.adapters.usage_product_surfaces import USAGE_BY_FUNCTION_ID
from yoke_cli.commands.registry_product_surfaces import (
    PRODUCT_SURFACE_SUBCOMMAND_REGISTRY,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture()
def dispatched(monkeypatch):
    calls: list[dict] = []

    def _capture(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(machine, "dispatch_and_emit", _capture)
    return calls


@pytest.fixture()
def local_machine(monkeypatch, tmp_path):
    monkeypatch.setattr(machine, "_local_machine_id", lambda: MACHINE_ID)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return MACHINE_ID


@pytest.mark.parametrize(
    "route, function_id",
    [
        (("machine", "register"), "machine.register"),
        (("machine", "list"), "machine.list"),
        (("machine", "show"), "machine.show"),
        (("machine", "settings", "get"), "machine.settings.get"),
        (("machine", "settings", "set"), "machine.settings.set"),
    ],
)
def test_every_machine_route_names_its_registered_function(route, function_id):
    assert PRODUCT_SURFACE_SUBCOMMAND_REGISTRY[route][0] == function_id
    assert function_id in USAGE_BY_FUNCTION_ID


def test_register_sends_the_local_id_and_name(dispatched, local_machine):
    assert machine.machine_register(["--name", "workshop-mac"]) == 0
    payload = dispatched[0]["payload"]
    assert payload["machine_id"] == MACHINE_ID
    assert payload["name"] == "workshop-mac"


def test_show_defaults_to_this_machine(dispatched, local_machine):
    assert machine.machine_show([]) == 0
    assert dispatched[0]["payload"]["machine_id"] == MACHINE_ID


def test_machine_access_help_discloses_that_offers_are_not_enforced(capsys):
    for adapter in (
        machine.machine_show,
        machine.machine_settings_get,
        machine.machine_settings_set,
    ):
        with pytest.raises(SystemExit) as excinfo:
            adapter(["--help"])
        assert excinfo.value.code == 0
        assert "not enforced or consulted today" in capsys.readouterr().out


def test_settings_set_parses_a_json_value_and_accepts_a_bare_word(
    dispatched, local_machine
):
    assert (
        machine.machine_settings_set(["--path", "use.actor_ids", "--value", "[2,3]"])
        == 0
    )
    assert dispatched[0]["payload"]["value"] == [2, 3]
    assert (
        machine.machine_settings_set(["--path", "use.mode", "--value", "universe"]) == 0
    )
    assert dispatched[1]["payload"]["value"] == "universe"


def test_list_can_narrow_to_machines_the_caller_owns(dispatched, local_machine):
    assert machine.machine_list(["--mine"]) == 0
    assert dispatched[0]["payload"] == {"owned_only": True}


def test_a_machine_with_no_local_id_names_the_setup_recovery(monkeypatch):
    monkeypatch.setattr(machine, "_local_machine_id", machine._local_machine_id)
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.machine_id", lambda: None
    )
    with pytest.raises(SystemExit) as excinfo:
        machine.machine_show([])
    assert "yoke onboard" in str(excinfo.value)
