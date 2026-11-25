"""Relay package installs share uv's cache and clean up failed candidates."""

import os
from pathlib import Path
import subprocess

import pytest

from runtime.api.tools.session_relay_release_test_support import (
    RELEASE,
    fake_venv,
    relay_instance,
    runner_for,
)
from yoke_core.domain.relay_release_path import relay_venv_python
from yoke_core.tools import session_relay_release_packages as packages
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
    RelayReleaseError,
    relay_release_status,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release

pytestmark = pytest.mark.windows


def _pin(instance, runner):
    return pin_relay_release(
        instance=instance, served_build=RELEASE, create_venv=fake_venv, runner=runner,
    )


def _is_uv(argv):
    return argv[1:3] == ["pip", "install"]


def test_package_install_uses_isolated_uv_and_records_each_step(tmp_path, monkeypatch, capsys):
    iso_vars = (
        "UV_INDEX", "UV_INDEX_URL", "UV_INDEX_STRATEGY", "UV_DEFAULT_INDEX",
        "UV_NO_INDEX", "UV_EXTRA_INDEX_URL", "UV_FIND_LINKS", "UV_CONSTRAINT",
        "UV_OVERRIDE", "UV_BUILD_CONSTRAINT", "UV_REQUIREMENT", "UV_CONFIG_FILE",
        "UV_PYTHON", "VIRTUAL_ENV", "UV_EXCLUDE_NEWER", "UV_RESOLUTION",
        "UV_PRERELEASE", "UV_OFFLINE", "UV_NO_CACHE", "UV_SYSTEM_PYTHON",
        "UV_COMPILE_BYTECODE", "UV_LINK_MODE", "PYTHONPATH", "PYTHONHOME",
    )
    for key in iso_vars:
        monkeypatch.setenv(key, "ambient")
    cache = str(tmp_path / "uv-cache")
    monkeypatch.setenv("UV_CACHE_DIR", cache)
    uv = tmp_path / "uv"
    uv.touch()
    monkeypatch.setattr(packages.shutil, "which", lambda name: str(uv) if name == "uv" else None)
    instance = relay_instance(tmp_path)
    install_calls = []
    fake_runner = runner_for(RELEASE, [])

    def runner(argv, **kwargs):
        if _is_uv(argv):
            install_calls.append((argv, kwargs))
        return fake_runner(argv, **kwargs)

    assert _pin(instance, runner).current
    [(argv, options)] = install_calls
    [release_root] = (instance.state_dir / "releases").iterdir()
    assert argv[:10] == [
        str(uv), "pip", "install", "--python", str(relay_venv_python(release_root)),
        "--no-config", "--only-binary", ":all:", "--default-index", "https://pypi.org/simple",
    ]
    assert argv[10:] == [
        f"https://wheels.example.test/dist/releases/{RELEASE}/wheels/"
        f"yoke_{name}-{RELEASE}-py3-none-any.whl"
        for name in ("contracts", "cli", "harness", "core")
    ]
    assert "-m" not in argv
    assert not set(iso_vars).intersection(options["env"])
    assert options["env"]["UV_CACHE_DIR"] == cache
    assert options["timeout"] == packages.RELAY_PACKAGE_INSTALL_TIMEOUT_SECONDS == 600

    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("relay install:")]
    assert [line.split(" took ")[0] for line in lines] == [
        "relay install: runtime", "relay install: release venv",
        "relay install: dependencies", "relay install: verify",
    ]
    for line in lines:
        elapsed, unit = line.split(" took ")[1].split()
        assert float(elapsed) >= 0 and unit == "s"


def test_dependency_timeout_records_failure_and_releases_lock(tmp_path):
    instance = relay_instance(tmp_path)
    healthy_runner = runner_for(RELEASE, [])

    def runner(argv, **kwargs):
        if _is_uv(argv):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return healthy_runner(argv, **kwargs)

    with pytest.raises(RelayReleaseError, match="did not finish within 600 s") as raised:
        _pin(instance, runner)
    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    releases = instance.state_dir / "releases"
    assert list(releases.iterdir()) == []
    status = relay_release_status(instance=instance, refresh_served=False, runner=runner)
    assert status.error_code == RELAY_RELEASE_FETCH_FAILED
    assert "did not finish within 600 s" in status.error_message

    abandoned = releases / "abandoned-unverified"
    abandoned.mkdir()
    (abandoned / "partial").touch()
    assert _pin(instance, healthy_runner).current
    assert not abandoned.exists()
    assert len(list(releases.iterdir())) == 1


def test_missing_uv_refuses_with_official_install_recovery(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    monkeypatch.setattr(packages.shutil, "which", lambda _name: None)
    monkeypatch.setattr(packages.Path, "home", lambda: tmp_path)

    with pytest.raises(RelayReleaseError, match="uv is required") as raised:
        _pin(instance, runner_for(RELEASE, []))

    assert raised.value.code == RELAY_RELEASE_INSTALL_FAILED
    assert "official installer" in str(raised.value)
    assert "yoke --env prod relay install" in str(raised.value)
    assert list((instance.state_dir / "releases").iterdir()) == []


def test_package_install_finds_uv_in_local_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(packages.shutil, "which", lambda _name: None)
    monkeypatch.setattr(packages.Path, "home", lambda: tmp_path)
    uv = tmp_path / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    uv.parent.mkdir(parents=True)
    uv.touch()
    calls: list[list[str]] = []
    packages.install_release_packages(
        Path("candidate-python"), release=RELEASE,
        index="https://wheels.example.test/simple/", environment="prod",
        runner=runner_for(RELEASE, calls),
    )
    assert calls[0][0] == str(uv)
