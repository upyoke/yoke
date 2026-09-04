"""The standing relay is installed atomically from its environment release."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config.session_relay_instance import resolve_relay_instance
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
    RelayReleaseError,
    distribution_index_for_instance,
    relay_release_status,
    release_version_from_build,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release


RELEASE = "0.1.1+launch.365"
NEXT_RELEASE = "0.1.1+launch.366"


def _config(tmp_path: Path, api_url: str = "https://relay.example.test/api") -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "prod": True,
                        "api_url": api_url,
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _instance(tmp_path: Path, api_url: str = "https://relay.example.test/api"):
    return resolve_relay_instance(
        config_path=_config(tmp_path, api_url),
        environment="prod",
        yoke_home=tmp_path / "state",
    )


def _fake_venv(path: Path) -> None:
    binary = path / "bin"
    binary.mkdir(parents=True)
    (binary / "python").touch()
    (binary / "yoke").touch()


def _runner_for(release: str, calls: list[list[str]]):
    def run(command, **_kwargs):
        argv = list(command)
        calls.append(argv)
        stdout = f"{release}\n" if "-c" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    return run


def test_handshake_build_is_an_exact_immutable_wheel_version() -> None:
    assert release_version_from_build(f"v{RELEASE}") == RELEASE
    with pytest.raises(RelayReleaseError, match="immutable release segment"):
        release_version_from_build("v0.1.1")


@pytest.mark.parametrize(
    ("api_url", "expected"),
    (
        ("https://app.upyoke.com/api/orgs/demo", "https://api.upyoke.com/simple/"),
        (
            "https://app.stage.upyoke.com/api/orgs/demo",
            "https://api.stage.upyoke.com/simple/",
        ),
        ("https://relay.example.test/api", "https://relay.example.test/simple/"),
    ),
)
def test_distribution_index_belongs_to_the_selected_environment(
    tmp_path: Path, api_url: str, expected: str
) -> None:
    assert distribution_index_for_instance(_instance(tmp_path, api_url)) == expected


def test_successful_pin_installs_a_wheel_then_swaps_the_stable_venv(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    calls: list[list[str]] = []

    status = pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=_fake_venv,
        runner=_runner_for(RELEASE, calls),
    )

    assert status.current
    assert status.pinned_release == RELEASE
    assert status.served_build == f"v{RELEASE}"
    assert status.executable == instance.state_dir / "venv" / "bin" / "yoke"
    assert (instance.state_dir / "venv").is_symlink()
    install = calls[0]
    assert install[-1] == f"yoke-core=={RELEASE}"
    assert install[install.index("--extra-index-url") + 1] == (
        "https://relay.example.test/simple/"
    )
    assert install[install.index("--only-binary") + 1] == ":all:"


def test_same_served_build_reuses_the_verified_install(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    calls: list[list[str]] = []
    pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=_fake_venv,
        runner=_runner_for(RELEASE, calls),
    )
    original_target = (instance.state_dir / "venv").resolve()

    reused = pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=lambda _path: pytest.fail("same release created another venv"),
        runner=lambda *_args, **_kwargs: pytest.fail("same release ran pip"),
    )

    assert reused.current
    assert (instance.state_dir / "venv").resolve() == original_target


def test_fetch_failure_keeps_the_last_working_install_and_records_recovery(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=_fake_venv,
        runner=_runner_for(RELEASE, []),
    )
    original_target = (instance.state_dir / "venv").resolve()

    def fail(command, **_kwargs):
        argv = list(command)
        return subprocess.CompletedProcess(argv, 1, "", "index unavailable")

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(
            instance=instance,
            served_build=f"v{NEXT_RELEASE}",
            create_venv=_fake_venv,
            runner=fail,
        )

    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert "kept pinned release" in str(raised.value)
    assert "relay install" in str(raised.value)
    assert (instance.state_dir / "venv").resolve() == original_target
    observed = relay_release_status(instance=instance, refresh_served=False)
    assert observed.pinned_release == RELEASE
    assert observed.error_code == RELAY_RELEASE_FETCH_FAILED
    assert "Recovery:" in observed.error_message


def test_handshake_failure_is_named_and_records_recovery(tmp_path: Path) -> None:
    instance = _instance(tmp_path)

    def fail_handshake(_environment: str):
        raise TimeoutError("manifest timed out")

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(instance=instance, fetch_manifest=fail_handshake)

    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert "handshake failed" in str(raised.value)
    assert "relay install" in str(raised.value)
    observed = relay_release_status(instance=instance, refresh_served=False)
    assert observed.error_code == RELAY_RELEASE_FETCH_FAILED


def test_local_install_failure_keeps_the_last_working_release(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=_fake_venv,
        runner=_runner_for(RELEASE, []),
    )
    original_target = (instance.state_dir / "venv").resolve()

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(
            instance=instance,
            served_build=f"v{NEXT_RELEASE}",
            create_venv=lambda _path: (_ for _ in ()).throw(
                OSError("venv directory unavailable")
            ),
        )

    assert raised.value.code == RELAY_RELEASE_INSTALL_FAILED
    assert "venv directory unavailable" in str(raised.value)
    assert (instance.state_dir / "venv").resolve() == original_target


def test_status_compares_the_pinned_release_with_a_fresh_handshake(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    pin_relay_release(
        instance=instance,
        served_build=f"v{RELEASE}",
        create_venv=_fake_venv,
        runner=_runner_for(RELEASE, []),
    )

    current = relay_release_status(
        instance=instance,
        fetch_manifest=lambda _env: {"server_engine_version": NEXT_RELEASE},
    )

    assert current.pinned_release == RELEASE
    assert current.served_build == f"v{NEXT_RELEASE}"
    assert not current.current
