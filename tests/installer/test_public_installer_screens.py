"""Behavior tests for the condensed install.py setup screens.

The install helper renders one friendly screen per outcome (fresh success,
already-installed no-op, failure) plus PATH remediation. The exact-byte gates
live in ``test_installer_goldens.py``; these tests cover the logic — version
normalization, the already-installed/failure branches, and PATH advice — across
combinations a single golden does not.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from public_installer_helpers import (
    RecordingRunner,
    branded_installer_glyphs as branded_installer_glyphs,
    load_installer,
    write_channel,
)


def _options(installer_mod, **overrides):
    base = dict(
        channel="stable",
        version=None,
        yes=False,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_onboard=False,
    )
    base.update(overrides)
    return installer_mod.InstallOptions(**base)


def _status_ok(version: str = "2.0.0"):
    payload = json.dumps(
        {
            "runtime": {
                "package_versions": {
                    "yoke-cli": version,
                    "yoke-contracts": version,
                    "yoke-harness": version,
                    "yoke-core": version,
                },
            },
            "connection": {"client_authority": "api", "transport": "https"},
        }
    )
    return subprocess.CompletedProcess(["yoke", "status", "--json"], 0, payload, "")


def _installed_yoke_path(tmp_path: Path, monkeypatch) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    yoke_bin = bin_dir / "yoke"
    yoke_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke_bin.chmod(0o755)
    monkeypatch.setenv("XDG_BIN_HOME", str(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return str(yoke_bin)


def test_advise_path_silent_when_yoke_on_path() -> None:
    # When yoke is already on PATH for this process, the path advice stays
    # silent — the setup that follows implies it.
    installer_mod = load_installer()
    output = io.StringIO()
    installer = installer_mod.Installer(
        _options(installer_mod),
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    installer._advise_path()

    assert output.getvalue() == ""


def test_advise_path_uses_absolute_remediation_when_off_path() -> None:
    # Skipping PATH prints an absolute-path remediation that works without
    # yoke on PATH yet.
    installer_mod = load_installer()
    output = io.StringIO()
    installer = installer_mod.Installer(
        _options(installer_mod),
        which=lambda name: None,
        stdout=output,
    )

    installer._advise_path()

    assert "~/.local/bin/yoke path fix" in output.getvalue()


def test_display_version_normalizes_dev_build() -> None:
    installer_mod = load_installer()
    assert installer_mod._display_version("0.1.1.dev16368+g8be5987c") == (
        "0.1.1 (dev g8be5987c)"
    )
    # A clean release passes through unchanged; empty stays empty.
    assert installer_mod._display_version("0.1.1") == "0.1.1"
    assert installer_mod._display_version("") == ""


def test_already_installed_screen_when_uv_reports_no_op(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="yoke-cli v2.0.0 is already installed",
        responses={
            (yoke_bin, "status", "--json"): _status_ok(),
            (yoke_bin, "--version"): subprocess.CompletedProcess(
                [yoke_bin, "--version"], 0, "2.0.0\n", ""
            ),
        },
    )
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    installer.run()

    rendered = output.getvalue()
    assert runner.commands[0][:4] == ["uv", "tool", "install", "yoke-cli==2.0.0"]
    assert "--config-file" in runner.commands[0]
    assert "☀ Yoke v2.0.0 already installed" in rendered
    assert "☀ Yoke v2.0.0 is ready" not in rendered
    assert "☀ Starting Yoke onboard…" not in rendered


def test_failure_screen_prints_reason_and_rerun(tmp_path: Path) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    output = io.StringIO()
    runner = RecordingRunner(
        rc=1,
        stderr="error: failed to resolve yoke-cli from the index",
    )
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    try:
        installer.run()
    except installer_mod.InstallError:
        pass
    else:
        raise AssertionError("expected the uv failure to raise InstallError")

    rendered = output.getvalue()
    assert "☀ Install failed" in rendered
    assert "✗ Couldn't install Yoke." in rendered
    assert "error: failed to resolve yoke-cli from the index" in rendered
    assert f"curl -fsSL {release['base_url']}/install | bash" in rendered
    assert "curl -fsSL https://api.upyoke.com/install | bash" not in rendered
    # The success screen never renders on a failed install.
    assert "☀ Starting Yoke onboard…" not in rendered


def test_channel_resolution_failure_prints_reason_and_rerun() -> None:
    installer_mod = load_installer()
    output = io.StringIO()
    runner = RecordingRunner()

    def failing_fetcher(url: str) -> bytes:
        raise installer_mod.InstallError(f"could not fetch {url}: HTTP Error 403")

    installer = installer_mod.Installer(
        _options(
            installer_mod,
            base_url="https://api.stage.upyoke.com",
            channel="missing-channel",
        ),
        fetcher=failing_fetcher,
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    try:
        installer.run()
    except installer_mod.InstallError:
        pass
    else:
        raise AssertionError("expected channel fetch failure")

    rendered = output.getvalue()
    assert runner.commands == []
    assert "☀ Install failed" in rendered
    assert "✗ Couldn't find a Yoke release to install." in rendered
    assert "missing-channel" in rendered
    assert "HTTP Error 403" in rendered
    assert "Try again:" in rendered
    assert "curl -fsSL https://api.stage.upyoke.com/install | bash" in rendered
    assert "Traceback" not in rendered
