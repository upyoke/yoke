"""Self-host setup and upgrades obey the recorded install authority."""

import json

import pytest

from runtime.api.fixtures.machine_config_test import select_machine_config_file
from yoke_cli.config.onboard_self_host_server import DockerPrerequisites
from yoke_cli.self_host import bundle, release_target, upgrade

STAGE = "https://api.stage.upyoke.com"
PRODUCTION = "https://api.upyoke.com"
VERSION = "0.2.0.202610140401"


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    path = tmp_path / "machine.json"
    select_machine_config_file(monkeypatch, path)
    monkeypatch.setattr(upgrade, "_require_packaged_install", lambda: None)
    monkeypatch.setattr(
        upgrade, "_CHECK_DOCKER", lambda: DockerPrerequisites("docker")
    )
    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", "https://ignored.example")
    monkeypatch.setenv("YOKE_CHANNEL", "ignored")
    return path


def _record(path, origin=STAGE, channel="latest"):
    path.write_text(json.dumps({"settings": {"distribution": {
        "origin": origin, "channel": channel,
    }}}))


def _existing(tmp_path):
    directory = tmp_path / "bundle"
    bundle.write_bundle(
        directory=str(directory), admin_name="Ada Lovelace", image="example/server:old"
    )
    return directory


@pytest.mark.parametrize("origin", [STAGE, PRODUCTION])
@pytest.mark.parametrize("channel", [None, "stable"])
@pytest.mark.posix_only(reason="server bundles run on Linux or WSL2; native Windows clients refuse hosting (decision 15871)")
def test_upgrade_fetches_recorded_origin_and_selected_channel(
    machine, tmp_path, monkeypatch, origin, channel
):
    _record(machine, origin=origin)
    directory = _existing(tmp_path)
    selected_channel = channel or "latest"
    seen = []

    def fetch(url):
        seen.append(url)
        return json.dumps({
            "schema_version": 3, "channel": selected_channel, "version": VERSION,
            "migration_history": {"source_commit": "a" * 40},
            "installer": {"python_url": f"{origin}/dist/install.py"},
        }).encode()

    monkeypatch.setattr(release_target, "_FETCH_BYTES", fetch)
    plan = upgrade.plan_upgrade(directory=str(directory), channel=channel)
    assert seen == [f"{origin}/dist/channels/{selected_channel}.json"]
    assert plan.target.base_url == origin
    assert plan.target.channel == selected_channel


@pytest.mark.parametrize("origin", [STAGE, PRODUCTION])
@pytest.mark.posix_only(reason="server bundles run on Linux or WSL2; native Windows clients refuse hosting (decision 15871)")
def test_setup_fetches_installed_release_from_recorded_origin(
    machine, tmp_path, monkeypatch, origin
):
    _record(machine, origin=origin)
    monkeypatch.setattr(release_target, "local_handshake_version", lambda: VERSION)
    seen = []

    def fetch(url):
        seen.append(url)
        return json.dumps({"artifact": {
            "engine_version": VERSION, "source_commit": "a" * 40,
        }}).encode()

    monkeypatch.setattr(release_target, "_FETCH_BYTES", fetch)
    report = bundle.write_bundle(
        directory=str(tmp_path / "bundle"), admin_name="Ada Lovelace"
    )
    assert seen == [f"{origin}/dist/releases/{VERSION}/migration-history.json"]
    assert report["image"].endswith(f":{VERSION}")


@pytest.mark.parametrize("operation", [
    "setup",
    pytest.param("upgrade", marks=pytest.mark.posix_only(
        reason="server bundles run on Linux or WSL2; native Windows clients refuse hosting (decision 15871)"
    )),
])
@pytest.mark.parametrize("config, code", [
    ({}, "distribution_origin_missing"),
    ({"settings": {"distribution": {"origin": "invalid", "channel": "latest"}}},
     "distribution_origin_invalid"),
    ({"settings": {"distribution": {"origin": STAGE, "channel": "bad channel"}}},
     "distribution_channel_invalid"),
    (None, "distribution_config_unreadable"),
])
def test_distribution_refusal_names_repair_without_fetching(
    machine, tmp_path, monkeypatch, operation, config, code
):
    machine.write_text(json.dumps(config) if config is not None else "{invalid")
    monkeypatch.setattr(
        release_target, "_FETCH_BYTES", lambda url: pytest.fail(f"unexpected fetch {url}")
    )
    if operation == "upgrade":
        directory = _existing(tmp_path)
        with pytest.raises(upgrade.SelfHostUpgradeError) as raised:
            upgrade.plan_upgrade(directory=str(directory))
        assert raised.value.code == "distribution-origin"
        diagnostic = " ".join(raised.value.detail_lines)
    else:
        with pytest.raises(bundle.SelfHostBundleError) as raised:
            bundle.write_bundle(
                directory=str(tmp_path / "bundle"), admin_name="Ada Lovelace"
            )
        diagnostic = str(raised.value)
    assert code in diagnostic
    assert "yoke settings set distribution" in diagnostic


@pytest.mark.posix_only(reason="server bundles run on Linux or WSL2; native Windows clients refuse hosting (decision 15871)")
def test_explicit_image_needs_no_distribution(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        release_target, "_FETCH_BYTES", lambda url: pytest.fail(f"unexpected fetch {url}")
    )
    assert _existing(tmp_path).is_dir()


@pytest.mark.posix_only(reason="server bundles run on Linux or WSL2; native Windows clients refuse hosting (decision 15871)")
def test_source_checkout_setup_still_resolves_git_image(machine, tmp_path, monkeypatch):
    _record(machine)
    monkeypatch.setattr(release_target, "local_handshake_version", lambda: "")
    monkeypatch.setattr(
        release_target, "_FETCH_BYTES", lambda url: pytest.fail(f"unexpected fetch {url}")
    )
    report = bundle.write_bundle(
        directory=str(tmp_path / "bundle"), admin_name="Ada Lovelace"
    )
    assert len(report["source_commit"]) == 40
    assert report["image"].endswith(f":{report['matched_cli_version']}")


def test_release_resolvers_require_an_explicit_origin():
    for resolver in (release_target.current_release_target,
                     release_target.channel_release_target):
        with pytest.raises(TypeError, match="base_url"):
            resolver()
    with pytest.raises(release_target.ReleaseTargetError):
        release_target.distribution_base_url("")
