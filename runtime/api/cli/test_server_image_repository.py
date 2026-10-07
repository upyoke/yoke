"""Repository selection stays consistent across onboarding and upgrades."""

import json
from types import SimpleNamespace
import pytest

from yoke_cli.config import server_image_repository as repository
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.config import onboard_wizard_image_repository as wizard
from yoke_cli.self_host import release_target, bundle, upgrade
from yoke_contracts.server_image import PUBLISHED_SERVER_IMAGE_REPOSITORY


def test_repository_round_trip_preserves_other_settings(tmp_path):
    path = tmp_path / "machine" / "config.json"
    value = "registry.example:5000/team/yoke"
    repository.save(value, path=path)
    payload = json.loads(path.read_text())
    payload["settings"]["unrelated"] = "preserved"
    path.write_text(json.dumps(payload))
    repository.save(value, path=path)
    assert repository.configured(path=path) == value
    assert json.loads(path.read_text())["settings"]["unrelated"] == "preserved"


def test_missing_override_uses_one_published_default(tmp_path):
    assert (
        repository.configured(path=tmp_path / "missing")
        == PUBLISHED_SERVER_IMAGE_REPOSITORY
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://registry/team/yoke",
        "registry/team/yoke:latest",
        "registry/team/yoke@sha256:abc",
        "user:password@registry/yoke",
        "Upper/repo",
        "registry/repo\n",
    ],
)
def test_invalid_repository_names_recovery(value):
    with pytest.raises(ValueError, match="server_image_repository_invalid"):
        repository.validate(value)
    assert wizard._input_error(value)


def test_configured_repository_selects_upgrade_and_initial_image(tmp_path, monkeypatch):
    path = tmp_path / "machine" / "config.json"
    value = "registry.example:5000/private/yoke"
    repository.save(value, path=path)
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(path))
    commit = "a" * 40
    monkeypatch.setattr(release_target, "local_handshake_version", lambda: "1.2.3")

    def fetch(url):
        if "channels" in url:
            return json.dumps(
                {
                    "schema_version": 3,
                    "channel": "stable",
                    "version": "1.2.3",
                    "migration_history": {"source_commit": commit},
                    "installer": {"python_url": "https://dist.example/dist/install.py"},
                }
            ).encode()
        return json.dumps(
            {"artifact": {"engine_version": "1.2.3", "source_commit": commit}}
        ).encode()

    monkeypatch.setattr(release_target, "_FETCH_BYTES", fetch)
    assert (
        release_target.current_release_target(base_url="https://dist.example").image
        == f"{value}:{commit[:12]}"
    )
    target = tmp_path / "bundle"
    bundle.write_bundle(
        admin_name="Ada Lovelace",
        directory=str(target),
        image="registry.example/private/yoke:old",
    )
    monkeypatch.setattr(upgrade, "_require_packaged_install", lambda: None)
    monkeypatch.setattr(
        upgrade, "_CHECK_DOCKER", lambda: server.DockerPrerequisites("docker")
    )
    monkeypatch.setattr(
        release_target,
        "distribution_base_url",
        lambda _value=None: "https://dist.example",
    )
    plan = upgrade.plan_upgrade(directory=str(target))
    assert plan.target.image == f"{value}:{commit[:12]}"


def test_wizard_preview_changes_repository_without_writes(tmp_path):
    path = tmp_path / "machine" / "config.json"
    setup = server.new_setup(config_path=str(path), directory=str(tmp_path / "bundle"))
    inputs = {}
    shell = SimpleNamespace(
        result=SimpleNamespace(config_path=str(path)), _self_host_setup=setup
    )
    shell._goto_input = lambda *args, **kwargs: inputs.update(kwargs)
    shell._goto = lambda view: None
    wizard.prompt(shell, setup)
    assert inputs["validate"]("registry.example/fork/yoke") is None
    inputs["on_done"]("registry.example/fork/yoke")
    assert setup.image_repository == "registry.example/fork/yoke"
    assert any(setup.image_repository in line for line in wizard.preview_lines(setup))
    assert not path.exists()


def test_provision_uses_and_saves_wizard_repository(tmp_path, monkeypatch):
    path = tmp_path / "machine" / "config.json"
    setup = server.new_setup(config_path=str(path), directory=str(tmp_path / "bundle"))
    setup.image_repository = "registry.example/fork/yoke"
    seen = {}

    def write(**kwargs):
        seen.update(kwargs)
        return {"directory": str(setup.directory)}

    monkeypatch.setattr(bundle, "write_bundle", write)
    server._ensure_wizard_bundle(setup)
    assert seen["image_repository"] == setup.image_repository
    assert repository.configured(path=path) == setup.image_repository


def test_wizard_repository_choice_validates_and_returns_to_preview(
    tmp_path, monkeypatch
):
    import asyncio
    from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_self_host import (
        _app,
        _open_preview,
        _body_text,
    )
    from runtime.api.cli.onboard_wizard_test_helpers import stub_path_doctor, type_text

    stub_path_doctor(monkeypatch)
    app, _ = _app(tmp_path)

    async def scenario():
        async with app.run_test() as pilot:
            await _open_preview(pilot)
            await pilot.press("down", "down", "enter")
            await pilot.press("ctrl+a", "ctrl+k")
            await type_text(pilot, "registry.example/fork/yoke")
            await pilot.press("enter")
            await pilot.pause()
            assert "Image repository: registry.example/fork/yoke" in _body_text(app)
            assert app._self_host_setup.image_repository == "registry.example/fork/yoke"
            assert not (tmp_path / "config.json").exists()

    asyncio.run(scenario())
