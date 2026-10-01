"""Private relay wheels come only from the install's recorded distribution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.tools.session_relay_release_test_support import RELEASE, relay_instance
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RelayReleaseError,
    distribution_index_for_instance,
    relay_release_status,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release


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
    tmp_path: Path, record: dict | None, reason: str
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
    assert "yoke --env prod relay install" in message
    assert "secret@" not in message
    observed = relay_release_status(instance=instance, refresh_served=False)
    assert observed.error_code == RELAY_RELEASE_FETCH_FAILED
    assert reason in observed.error_message
    assert not (instance.state_dir / "release").exists()


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
