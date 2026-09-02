from __future__ import annotations

import json
import stat
import uuid

import pytest

from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import schema_connections
from yoke_contracts.machine_config import runtime as machine_runtime


def test_canonical_example_is_valid_machine_config() -> None:
    payload = contract.canonical_example_payload()

    assert payload["schema_version"] == 1
    assert str(uuid.UUID(payload["machine_id"])) == payload["machine_id"]
    assert payload["active_env"] == "prod"
    assert payload["connections"]["prod"]["transport"] == "https"
    assert payload["connections"]["prod"][contract.PROD_FLAG_KEY] is True
    assert payload["connections"]["source-dev-admin"]["transport"] == "local-postgres"
    assert payload["connections"]["source-dev-admin"][contract.PROD_FLAG_KEY] is False
    authority = payload["connections"]["source-dev-admin"]["authority"]
    assert authority["location"]["stack"] == "app-prod"
    assert authority["location"]["database_name"] == "app_prod"
    assert payload["connections"]["stage"]["transport"] == "https"
    assert payload["connections"]["stage"][contract.PROD_FLAG_KEY] is False
    entry = payload["projects"][0]
    assert entry["checkout"] and entry["env"] == "prod"
    assert "board" not in entry
    assert contract.validate_payload(payload) == []
    assert json.loads(contract.canonical_example_text()) == payload


def test_machine_id_contract_rejects_noncanonical_values() -> None:
    payload = contract.canonical_example_payload()
    payload["machine_id"] = "NOT-A-UUID"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "machine_id_invalid" for issue in issues)


def test_machine_id_is_created_once_and_written_privately(tmp_path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"schema_version": 1}\n', encoding="utf-8")

    first = machine_runtime.ensure_machine_id(config)
    second = machine_runtime.ensure_machine_id(config)

    assert first == second == machine_runtime.machine_id(config)
    assert str(uuid.UUID(first)) == first
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_machine_id_initialization_requires_existing_config(tmp_path) -> None:
    with pytest.raises(machine_runtime.MachineConfigError, match="configured"):
        machine_runtime.ensure_machine_id(tmp_path / "missing.json")


def test_env_override_routes_to_configured_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = contract.canonical_example_payload()

    monkeypatch.setenv(contract.ENV_OVERRIDE, "stage")

    assert contract.selected_env(payload) == "stage"
    connection = contract.active_connection(payload)
    assert connection["env"] == "stage"
    assert connection["transport"] == "https"


def test_active_connection_rejects_unconfigured_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = contract.canonical_example_payload()

    monkeypatch.setenv(contract.ENV_OVERRIDE, "nope")

    with pytest.raises(contract.MachineConfigContractError, match="nope"):
        contract.active_connection(payload)


def test_validate_flags_unknown_active_and_requested_env() -> None:
    payload = contract.canonical_example_payload()
    payload["active_env"] = "ghost"

    codes = {
        issue.code
        for issue in contract.validate_payload(payload, explicit_env="phantom")
    }

    assert "active_env_unknown" in codes
    assert "env_unknown" in codes


def test_validate_rejects_non_boolean_prod_flag() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["stage"][contract.PROD_FLAG_KEY] = "false"

    issues = contract.validate_payload(payload)

    assert any(issue.code == "prod_flag_invalid" for issue in issues)


def test_validate_requires_connections_and_active_env() -> None:
    codes = {issue.code for issue in contract.validate_payload({"schema_version": 1})}

    assert "connections_required" in codes
    assert "active_env_required" in codes


def test_incomplete_tunnel_block_is_a_validation_error() -> None:
    payload = contract.canonical_example_payload()
    tunnel = payload["connections"]["source-dev-admin"]["postgres"]["tunnel"]
    del tunnel["remote_port"]
    del tunnel["identity_file"]

    issues = contract.validate_payload(payload)

    [issue] = [i for i in issues if i.code == "tunnel_incomplete"]
    assert "identity_file" in issue.message
    assert "remote_port" in issue.message


def test_absent_tunnel_block_is_valid() -> None:
    payload = contract.canonical_example_payload()
    del payload["connections"]["source-dev-admin"]["postgres"]["tunnel"]

    assert contract.validate_payload(payload) == []


def test_local_postgres_envs_lists_only_local_transports() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["cloud-beta"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: False,
        "credential_source": {"kind": "env", "name": "X"},
    }
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "Y"},
    }

    assert contract.local_postgres_envs(payload) == [
        "cloud-beta",
        "source-dev-admin",
    ]
    assert contract.local_postgres_envs(payload, include_prod=True) == [
        "cloud-beta",
        "prod-db-admin",
        "source-dev-admin",
    ]
    assert contract.local_postgres_envs({}) == []
    assert contract.local_postgres_envs(None) == []


def test_env_override_teaching_names_why_envs_and_recipe() -> None:
    payload = contract.canonical_example_payload()
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }
    payload["active_env"] = "stage"

    # Example command: direct SQL is a genuinely local-postgres-only
    # surface (wrapped `yoke` reads relay over https).
    recipe = 'python3 -m yoke_core.cli.db_router query "SELECT 1"'
    text = contract.env_override_teaching(
        payload,
        selected_env="stage",
        transport="https",
        command=recipe,
    )

    assert "'stage'" in text and "https" in text
    assert "requires a local-postgres env" in text
    assert f"{contract.ENV_OVERRIDE}=source-dev-admin {recipe}" in text
    assert "configured local-postgres envs: prod-db-admin, source-dev-admin" in text
    assert "--env source-dev-admin" in text


def test_env_override_teaching_without_local_env_teaches_config() -> None:
    payload = contract.canonical_example_payload()
    del payload["connections"]["source-dev-admin"]
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }

    text = contract.env_override_teaching(
        payload,
        selected_env="stage",
        transport="https",
    )

    assert "No local-postgres env is configured" in text
    assert "yoke config example" in text
    assert "prod-db-admin" not in text


def test_invocation_recipe_reconstructs_module_and_script_shapes() -> None:
    module_form = schema_connections._invocation_recipe(
        argv=["/x/db_router.py", "query", "SELECT 1"],
        main_spec_name="yoke_core.cli.db_router",
        interpreter="/venv/bin/python3",
    )
    assert module_form == (
        "/venv/bin/python3 -m yoke_core.cli.db_router query 'SELECT 1'"
    )

    package_form = schema_connections._invocation_recipe(
        argv=["/x/__main__.py"],
        main_spec_name="some.pkg.__main__",
        interpreter="/venv/bin/python3",
    )
    assert package_form == "/venv/bin/python3 -m some.pkg"

    script_form = schema_connections._invocation_recipe(
        argv=["/usr/local/bin/yoke", "status"],
        main_spec_name="",
    )
    assert script_form == "yoke status"


def test_invocation_recipe_names_the_running_interpreter_not_ambient_python() -> None:
    """A module recipe must be runnable by whoever reads it.

    The process that hit the error reached its imports through
    ``sys.executable``; ``python3`` on PATH is frequently a different
    interpreter that cannot import the module the recipe re-enters.
    """
    import sys

    recipe = schema_connections._invocation_recipe(
        argv=["/x/runtime.py", "YOK-1"],
        main_spec_name="yoke_cli.commands.merge_item_local_runtime",
    )

    assert recipe.startswith(sys.executable)
    assert not recipe.startswith("python3 ")


def test_env_override_teaching_prefers_the_selected_universe_admin_sibling() -> None:
    """The recipe must name the env holding the caller's own rows.

    A machine can configure several local-postgres connections that reach
    completely different universes. Naming whichever sorts first sends the
    operator to a database where their item does not exist.
    """
    payload = contract.canonical_example_payload()
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }
    payload["active_env"] = "prod"

    text = contract.env_override_teaching(
        payload,
        selected_env="prod",
        transport="https",
        command="yoke merge item X",
    )

    assert f"{contract.ENV_OVERRIDE}=prod-db-admin yoke merge item X" in text
    assert "administers the same universe as 'prod'" in text
    assert "configured local-postgres envs: prod-db-admin, source-dev-admin" in text
    # The alphabetically-first non-prod local env must not win over the pair.
    assert f"{contract.ENV_OVERRIDE}=source-dev-admin" not in text


def test_same_universe_env_pairing_is_symmetric_and_conservative() -> None:
    payload = {
        "connections": {
            "prod": {"transport": "https"},
            "prod-db-admin": {"transport": "local-postgres"},
            "stage": {"transport": "https"},
        }
    }

    assert contract.same_universe_db_admin_env(payload, "prod") == "prod-db-admin"
    assert contract.same_universe_https_env(payload, "prod-db-admin") == "prod"
    # An env whose counterpart is not configured pairs with nothing.
    assert contract.same_universe_db_admin_env(payload, "stage") == ""
    assert contract.same_universe_https_env(payload, "sandbox-db-admin") == ""
    # An admin label is never its own admin sibling, and a plain env is
    # never mistaken for one.
    assert contract.same_universe_db_admin_env(payload, "prod-db-admin") == ""
    assert contract.same_universe_https_env(payload, "prod") == ""
