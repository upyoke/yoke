"""Connection selection precedence and CLI inference without explicit overrides."""

import json
from types import SimpleNamespace

import pytest

from yoke_cli.config import connection_selection as cli
from yoke_cli.config import _editable_loader_template as loader
from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
    selected_env,
)
from yoke_contracts.machine_config.selection import connection_selection


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.chdir(tmp_path)
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    return {
        "active_env": "fallback",
        "connections": {"one": {"transport": "https"}, "two": {}},
        "connection_projects": {
            env: [{"checkout": str(root), "project_id": index}]
            for index, (env, root) in enumerate(zip(("one", "two"), roots), 1)
        },
    }


@pytest.mark.parametrize(
    "explicit,override,expected",
    [
        ("flag", "variable", "flag"),
        (None, "variable", "variable"),
        (None, "", "one"),
        ("one-db-admin", "", "one-db-admin"),
    ],
)
def test_override_precedence(config, monkeypatch, explicit, override, expected):
    monkeypatch.chdir(config["connection_projects"]["one"][0]["checkout"])
    monkeypatch.setenv("YOKE_ENV", override)
    assert selected_env(config, explicit) == expected


def test_admin_registration_uses_product_connection(config, monkeypatch):
    config["connection_projects"]["one-db-admin"] = config["connection_projects"].pop(
        "one"
    )
    monkeypatch.chdir(config["connection_projects"]["one-db-admin"][0]["checkout"])
    assert selected_env(config) == "one"
    del config["connections"]["one"]
    assert selected_env(config) == "fallback"


def test_deepest_checkout_and_path_boundary(config, monkeypatch, tmp_path):
    nested = tmp_path / "one" / "nested"
    nested.mkdir()
    config["connection_projects"]["two"][0]["checkout"] = str(nested)
    monkeypatch.chdir(nested)
    assert selected_env(config) == "two"
    sibling = tmp_path / "one-sibling"
    sibling.mkdir()
    monkeypatch.chdir(sibling)
    assert selected_env(config) == "fallback"


def test_equal_depth_ambiguity_is_named(config, monkeypatch):
    config["connection_projects"]["two"][0]["checkout"] = config["connection_projects"][
        "one"
    ][0]["checkout"]
    monkeypatch.chdir(config["connection_projects"]["one"][0]["checkout"])
    with pytest.raises(MachineConfigContractError) as failure:
        selected_env(config)
    assert str(failure.value).split(":", 1)[0] == "checkout_connection_ambiguous"


@pytest.mark.parametrize("maps", [None, {}, {"one": []}])
def test_unregistered_and_machine_fallback(config, maps):
    config["connection_projects"] = maps
    assert connection_selection(config) == ("fallback", "active_env")


def test_missing_fallback_still_allows_checkout(config, monkeypatch):
    config.pop("active_env")
    monkeypatch.chdir(config["connection_projects"]["one"][0]["checkout"])
    assert selected_env(config) == "one"


@pytest.mark.parametrize(
    "args,expected",
    [
        (["--project", "alpha"], "one"),
        (["--project=alpha"], "one"),
        (["items", "get", "ALPHA-3"], "one"),
        (["--project", "2"], "two"),
        (["--project", "missing"], "fallback"),
        (["items", "get", "MISSING-3"], "fallback"),
        (["db", "read", "ALPHA-3 in text"], "fallback"),
        (["watch", "--", "ALPHA-3"], "fallback"),
        (["env", "list"], "fallback"),
    ],
)
def test_scoped_project_reference(config, monkeypatch, args, expected):
    monkeypatch.setattr(cli.machine_config, "load_config", lambda: config)
    monkeypatch.setattr(
        cli,
        "_project_rows",
        lambda env: [
            {
                "id": 1 if env == "one" else 2,
                "slug": "alpha" if env == "one" else "beta",
                "public_item_prefix": "ALPHA" if env == "one" else "BETA",
            },
            {"id": 99, "slug": "unregistered", "public_item_prefix": "OTHER"},
        ],
    )
    with cli.command_connection(args, None):
        assert selected_env(config) == expected
        assert "YOKE_ENV" not in cli.os.environ
    assert selected_env(config) == "fallback"


def test_reference_collisions_fall_back_and_unregistered_rows_do_not_route(
    config, monkeypatch
):
    monkeypatch.setattr(
        cli,
        "_project_rows",
        lambda env: [
            {
                "id": 1 if env == "one" else 2,
                "slug": "shared",
                "public_item_prefix": "SHARED",
            },
            {"id": 99, "slug": "unregistered", "public_item_prefix": "OTHER"},
        ],
    )
    assert cli.referenced_connection(config, ["--project", "shared"]) == ""
    assert cli.referenced_connection(config, ["--project", "unregistered"]) == ""


def test_checkout_and_explicit_env_skip_reference_reads(config, monkeypatch):
    monkeypatch.setattr(cli.machine_config, "load_config", lambda: config)
    monkeypatch.setattr(
        cli, "_project_rows", lambda env: pytest.fail("unnecessary lookup")
    )
    monkeypatch.chdir(config["connection_projects"]["one"][0]["checkout"])
    with cli.command_connection(["--project", "beta"], None):
        assert connection_selection(config) == ("one", "checkout")
    monkeypatch.setenv("YOKE_ENV", "two")
    with cli.command_connection(["--project", "alpha"], "two"):
        assert connection_selection(config) == ("two", "explicit_flag")
    assert connection_selection(config) == ("two", "env_var")


def test_unavailable_reference_read_refuses_with_code(monkeypatch):
    from yoke_cli.transport import dispatcher

    monkeypatch.setattr(
        dispatcher,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(
            success=False, error=SimpleNamespace(code="unreachable")
        ),
    )
    with pytest.raises(MachineConfigContractError) as failure:
        cli._project_rows("one")
    assert (
        str(failure.value).split(":", 1)[0]
        == "project_reference_connection_unavailable"
    )


def test_loader_scans_inactive_connection(tmp_path):
    root = tmp_path / "source"
    marker = root / loader._CHECKOUT_MARKER
    marker.parent.mkdir(parents=True)
    marker.touch()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "active_env": "other",
                "connection_projects": {
                    "other": [],
                    "source": [{"checkout": str(root), "project_id": 1}],
                },
            }
        )
    )
    assert (
        loader.resolve_repo_root(environ={"YOKE_ENV": "other"}, config_path=config_path)
        == root
    )


def test_reassign_removes_only_the_same_checkout(config, tmp_path, monkeypatch):
    from runtime.api.fixtures.machine_config_test import select_machine_config_file
    from yoke_cli.config import writer

    config["connection_projects"]["two"].append(
        {
            "checkout": config["connection_projects"]["one"][0]["checkout"],
            "project_id": 3,
        }
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    select_machine_config_file(monkeypatch, config_path)
    monkeypatch.setenv("YOKE_ENV", "one")
    writer.register_project(tmp_path / "one", 1, reassign=True, path=config_path)
    entries = json.loads(config_path.read_text())["connection_projects"]
    assert entries["two"] == [{"checkout": str(tmp_path / "two"), "project_id": 2}]
    assert entries["one"] == [{"checkout": str(tmp_path / "one"), "project_id": 1}]
