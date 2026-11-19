"""Project uninstall retires each checkout from its own connection's map.

Two universes each number their first project 1; uninstall runs from the
machine with whichever connection is active, so the checkout's registration
alone must name the map it belongs to (feedback 97105).
"""

import json
import os

import pytest

from yoke_contracts.testing.real_home_isolation import set_home
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_cli.config import writer
from yoke_cli.project_install import owned_cleanup, uninstall_commit
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.uninstall import uninstall
from yoke_core.domain.project_install_test_helpers import make_bundle
from runtime.api.cli.project_uninstall_test_support import git, read_json

SHARED = "project_uninstall_checkout_shared_with_other_connection"


@pytest.fixture
def two_universes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    set_home(monkeypatch, home)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    launcher = home / "bin/yoke"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(launcher.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a, **_k: {"value": "main"})
    config = tmp_path / "machine/config.json"
    for label in ("local", "self-hosted"):
        writer.set_connection(
            label,
            transport="https",
            api_url=f"https://{label}.invalid",
            token="fixture-only",
            path=config,
        )
    roots = {"local": tmp_path / "hp-local", "self-hosted": tmp_path / "hp-self-hosted"}
    for label, root in roots.items():
        monkeypatch.setenv("YOKE_ENV", label)
        root.mkdir()
        git(root, "init", "-b", "main")
        git(root, "config", "maintenance.auto", "false")
        git(root, "config", "gc.auto", "0")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.com")
        bundle = make_bundle()
        bundle["project_id"] = 1  # Each universe numbers its first project 1.
        apply_bundle(root, bundle, source="fixture")
        writer.register_project(root, 1, path=config)
        owned_cleanup.record_registration(root, 1, config)
        grant_folder_trust(root)
        git(root, "add", "-A")
        git(root, "commit", "--no-verify", "-m", "Fixture install")
    monkeypatch.delenv("YOKE_ENV")
    writer.set_active_env("local", path=config)
    return roots, config


@pytest.mark.parametrize("order", [("local", "self-hosted"), ("self-hosted", "local")])
def test_projects_all_retires_each_checkout_from_its_own_connection(
    two_universes, order
):
    roots, config = two_universes
    assert read_json(config)["connection_projects"] == {
        label: [{"checkout": str(root), "project_id": 1}]
        for label, root in roots.items()
    }
    for label in order:
        report = uninstall(roots[label], config_path=config)
        assert report["outcome"] == "complete", report
        assert report["local_cleanup"]["registration"]["status"] == "removed"
        assert not report["warnings"], report["warnings"]
    payload = read_json(config)
    assert payload["connection_projects"] == {"local": [], "self-hosted": []}
    assert payload["active_env"] == "local"


def test_checkout_under_two_connections_refuses_once(two_universes):
    roots, config = two_universes
    payload = read_json(config)
    payload["connection_projects"]["local"].append(
        {"checkout": str(roots["self-hosted"]), "project_id": 2}
    )
    config.write_text(json.dumps(payload))
    before = config.read_bytes()
    report = uninstall(roots["self-hosted"], config_path=config)
    assert report["outcome"] == "partial"
    assert config.read_bytes() == before
    refusals = [w for w in report["warnings"] if w.startswith(f"{SHARED}:")]
    assert len(refusals) == 1, report["warnings"]


def test_registration_only_checkout_retires_from_its_own_connection(
    two_universes, tmp_path
):
    roots, config = two_universes
    folder = tmp_path / "never-installed"
    folder.mkdir()
    payload = read_json(config)
    payload["connection_projects"]["self-hosted"].append(
        {"checkout": str(folder), "project_id": 2}
    )
    config.write_text(json.dumps(payload))
    report = uninstall(folder, config_path=config)
    assert report["outcome"] == "complete", report
    assert read_json(config)["connection_projects"] == {
        label: [{"checkout": str(root), "project_id": 1}]
        for label, root in roots.items()
    }


def test_branch_lookup_asks_the_connection_that_owns_the_checkout(
    two_universes, monkeypatch
):
    roots, config = two_universes
    writer.set_active_env("self-hosted", path=config)
    asked = []

    def dispatch(function_id, payload, config_path, **kwargs):
        asked.append((function_id, payload["project"], kwargs["env"]))
        return {"value": "main"}

    monkeypatch.setattr(uninstall_commit, "dispatch", dispatch)
    report = uninstall(roots["local"], config_path=config)
    assert report["outcome"] == "complete", report
    assert asked == [("projects.get", "1", "local")]
