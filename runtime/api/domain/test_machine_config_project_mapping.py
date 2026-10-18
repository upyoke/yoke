"""Project ids and checkout slots belong to their selected universe."""

import json

import pytest
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import runtime
from yoke_cli.config import machine_config, writer
from yoke_cli.commands.adapters.claims_work_folder_guard import render_folder_line
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from runtime.api.fixtures.machine_config_test import select_machine_config_file


@pytest.mark.parametrize(
    "env,connection",
    [
        ("prod", "prod"),
        ("prod-db-admin", "prod"),
        ("self-hosted", "self-hosted"),
    ],
)
def test_readers_isolate_colliding_project_ids(tmp_path, monkeypatch, env, connection):
    repos = {name: tmp_path / name for name in ("prod", "self-hosted")}
    for repo in repos.values():
        repo.mkdir()
    payload = contract.canonical_example_payload()
    payload["connections"]["prod-db-admin"] = {"transport": "local-postgres"}
    payload["connection_projects"] = {
        name: [{"checkout": str(repo), "project_id": 7}] for name, repo in repos.items()
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(payload))
    select_machine_config_file(monkeypatch, config)
    monkeypatch.setenv("YOKE_ENV", env)
    repo = repos[connection]
    other = repos["self-hosted" if connection == "prod" else "prod"]
    assert contract.project_entry_for_checkout(payload, repo) == {"project_id": 7}
    assert contract.project_entry_for_checkout(payload, other) == {}
    assert contract.mapped_checkouts(payload) == [(str(repo), 7)]
    assert runtime.project_id(repo, config) == 7
    assert runtime.project_id(other, config) is None
    assert runtime.installed_project_ids(config) == {7}
    assert [p.checkout for p in machine_config.configured_projects(config)] == [repo]
    assert checkout_for_project_id(7, config_path=config) == repo
    assert str(repo) in render_folder_line(7, "example", "ITEM", "Example work")
    missing = render_folder_line(8, "unmapped", "ITEM", "Example work")
    assert (
        f"yoke --env {connection} project register CHECKOUT --project-id 8" in missing
    )
    assert str(other) not in missing


def test_register_preserves_another_universe_and_reassigns_only_selected_slot(
    tmp_path, monkeypatch
):
    config = tmp_path / "config.json"
    payload = contract.canonical_example_payload()
    payload["connections"]["other"] = payload["connections"]["prod"]
    payload["connection_projects"] = {}
    config.write_text(json.dumps(payload))
    select_machine_config_file(monkeypatch, config)
    repos = [tmp_path / name for name in ("first", "other", "moved")]
    for repo in repos:
        repo.mkdir()
    for env, repo in zip(("prod", "other"), repos):
        monkeypatch.setenv("YOKE_ENV", env)
        receipt = writer.register_project(repo, 1, path=config)
        assert receipt["connection"] == env
    with pytest.raises(writer.MachineConfigWriteError, match="already routed"):
        writer.register_project(repos[2], 1, path=config)
    writer.register_project(repos[2], 1, reassign=True, path=config)
    entries = json.loads(config.read_text())["connection_projects"]
    assert entries == {
        "prod": [{"checkout": str(repos[0]), "project_id": 1}],
        "other": [{"checkout": str(repos[2]), "project_id": 1}],
    }


def test_reads_never_write_and_explicit_registration_imports_legacy_once(
    tmp_path, monkeypatch
):
    config = tmp_path / "config.json"
    payload = contract.canonical_example_payload()
    payload.pop("connection_projects")
    payload["projects"] = [{"checkout": str(tmp_path), "project_id": 1}]
    config.write_text(json.dumps(payload))
    select_machine_config_file(monkeypatch, config)
    monkeypatch.setenv("YOKE_ENV", "other")
    original = config.read_bytes()
    runtime.load_config(config)
    assert config.read_bytes() == original
    assert runtime.project_id(tmp_path, config) is None
    assert config.read_bytes() == original
    other = tmp_path / "other"
    other.mkdir()
    payload["connections"]["other"] = payload["connections"]["prod"]
    config.write_text(json.dumps(payload))
    writer.register_project(other, 1, path=config)
    upgraded = json.loads(config.read_text())
    assert upgraded["projects"] == payload["projects"]
    assert upgraded["connection_projects"] == {
        "prod": payload["projects"],
        "other": [{"checkout": str(other), "project_id": 1}],
    }
    before = config.read_bytes()
    assert runtime.project_id(other, config) == 1
    assert config.read_bytes() == before
    # Stale flat ids never return to routing after the one-time import.
    upgraded["projects"].append({"checkout": str(tmp_path / "stale"), "project_id": 99})
    config.write_text(json.dumps(upgraded))
    assert runtime.installed_project_ids(config) == {1}


def test_duplicate_project_refuses_with_recovery():
    projects = [
        {"checkout": "/co/a", "project_id": 1},
        {"checkout": "/co/b", "project_id": 1},
    ]
    with pytest.raises(
        contract.MachineConfigContractError,
        match="project_id_duplicate.*repair projects",
    ):
        contract.normalize_projects(projects)


def test_same_checkout_can_name_different_projects_per_connection(
    tmp_path, monkeypatch
):
    payload = {
        "active_env": "first",
        "connection_projects": {
            "first": [{"checkout": str(tmp_path), "project_id": 1}],
            "second": [{"checkout": str(tmp_path), "project_id": 2}],
        },
    }
    for env, expected in (("first", 1), ("second", 2)):
        monkeypatch.setenv("YOKE_ENV", env)
        assert contract.project_entry_for_checkout(payload, tmp_path) == {
            "project_id": expected
        }


def test_uninstall_preserves_checkout_used_by_another_connection(tmp_path, monkeypatch):
    from yoke_cli.project_install import owned_cleanup

    config = tmp_path / "config.json"
    payload = contract.canonical_example_payload()
    payload["connection_projects"] = {
        "prod": [{"checkout": str(tmp_path), "project_id": 1}],
        "stage": [{"checkout": str(tmp_path), "project_id": 2}],
    }
    config.write_text(json.dumps(payload))
    select_machine_config_file(monkeypatch, config)
    monkeypatch.setenv("YOKE_ENV", "prod")
    reasons = []
    monkeypatch.setattr(
        owned_cleanup,
        "revert_folder_trust",
        lambda root, exclusive_reason: reasons.append(exclusive_reason) or [],
    )
    before = config.read_bytes()
    result = owned_cleanup.cleanup(tmp_path, {"project_id": 1}, config)
    assert reasons == ["checkout_shared_with_other_connection"]
    assert result["registration"]["status"] == "preserved"
    assert not result["complete"]
    assert config.read_bytes() == before
