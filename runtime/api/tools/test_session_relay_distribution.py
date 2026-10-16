"""Private relay wheels come only from the install's recorded distribution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.tools.session_relay_release_test_support import (
    RELEASE,
    fake_venv,
    relay_instance,
    runner_for,
    reuse_only_runner,
)
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RelayReleaseError,
    distribution_index_for_instance,
    relay_release_status,
    release_version_from_build,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release


@pytest.mark.parametrize("build", ("0.2.0.202610150430", "v0.1.1+launch.365", "2.0.0"))
def test_handshake_build_is_an_exact_wheel_version(build: str) -> None:
    from packaging.version import Version

    assert release_version_from_build(build) == str(Version(build))
    with pytest.raises(RelayReleaseError, match="not a valid Yoke release version"):
        release_version_from_build("not-a-version")


@pytest.mark.parametrize(
    ("release", "encoded"),
    [
        ("0.2.0.202610150430", "0.2.0.202610150430"),
        ("0.1.1+launch.633", "0.1.1%2Blaunch.633"),
    ],
)
def test_served_build_installs_exact_origin_then_reuses(
    tmp_path: Path, release: str, encoded: str
) -> None:
    instance = relay_instance(tmp_path)
    calls: list[list[str]] = []
    status = pin_relay_release(
        instance=instance,
        fetch_manifest=lambda _env: {"server_engine_version": release},
        create_venv=fake_venv,
        runner=runner_for(release, calls),
    )
    assert status.current
    assert status.pinned_release == status.served_build == release
    assert calls[0][-4:] == [
        f"https://wheels.example.test/dist/releases/{encoded}/wheels/"
        f"yoke_{name}-{encoded}-py3-none-any.whl"
        for name in ("contracts", "cli", "harness", "core")
    ]
    assert calls[0][1:5] == ["-I", "-m", "pip", "--isolated"]
    assert "--extra-index-url" not in calls[0]
    prior = (instance.state_dir / "release").resolve()
    reused = pin_relay_release(
        instance=instance,
        served_build=release,
        create_venv=lambda _path: pytest.fail("current release created a venv"),
        runner=reuse_only_runner(release),
    )
    assert reused.current
    assert (instance.state_dir / "release").resolve() == prior


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (None, "distribution_origin_missing"),
        ({"origin": "", "channel": "private"}, "distribution_origin_missing"),
        (
            {"origin": "https://secret@wheels.test", "channel": "private"},
            "distribution_origin_invalid",
        ),
        (
            {"origin": "https://wheels.test/simple/", "channel": "private"},
            "distribution_origin_invalid",
        ),
        (
            {"origin": "https://wheels.test", "channel": ""},
            "distribution_channel_invalid",
        ),
    ],
)
def test_undeclared_or_invalid_distribution_refuses_before_install(
    tmp_path: Path, record: dict | None, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = relay_instance(tmp_path)
    payload = json.loads(instance.config_path.read_text())
    payload["settings"] = {"distribution": record}
    instance.config_path.write_text(json.dumps(payload))

    def unexpected_install(*_args, **_kwargs):
        pytest.fail("a refused distribution must not create a venv or invoke pip")

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(
            instance=instance,
            served_build=f"v{RELEASE}",
            create_venv=unexpected_install,
            create_runtime=unexpected_install,
            runner=unexpected_install,
        )

    message = str(raised.value)
    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert reason in message
    assert "requires a declared install distribution" in message
    assert "yoke config distribution set --origin URL --channel NAME" in message
    assert "yoke update --version VERSION" in message
    assert "official installer" in message
    assert "yoke --env prod relay status" in message
    assert "yoke --env prod relay install" in message
    assert "secret@" not in message
    observed = relay_release_status(instance=instance, refresh_served=False)
    assert observed.error_code == RELAY_RELEASE_FETCH_FAILED
    assert reason in observed.error_message
    assert not (instance.state_dir / "release").exists()

    from types import SimpleNamespace
    from yoke_cli.commands.adapters.session_control_relay_release import (
        release_status_payload,
    )

    monkeypatch.setattr(
        "yoke_cli.config.session_relay_instance.resolve_relay_instance",
        lambda **_kwargs: instance,
    )
    payload = release_status_payload(
        SimpleNamespace(environment=instance.environment), refresh_served=False
    )
    assert payload["release_recovery"] == message.split("Recovery: ", 1)[1]


def test_recorded_origin_is_normalized_without_reading_ambient_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = relay_instance(tmp_path, "http://[::1]:8765/api")
    payload = json.loads(instance.config_path.read_text())
    payload["settings"]["distribution"]["origin"] = "https://wheels.test:8443/"
    instance.config_path.write_text(json.dumps(payload))
    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", "https://other.test")
    assert (
        distribution_index_for_instance(instance) == "https://wheels.test:8443/simple/"
    )


def test_hosted_indexes_do_not_require_a_private_install_record(tmp_path: Path) -> None:
    instance = relay_instance(tmp_path, "https://app.upyoke.com/api/orgs/demo")
    payload = json.loads(instance.config_path.read_text())
    payload.pop("settings")
    instance.config_path.write_text(json.dumps(payload))
    assert distribution_index_for_instance(instance) == "https://api.upyoke.com/simple/"
