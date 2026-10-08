"""Dry-run succeeds only when the chosen origin has published that version."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from public_installer_helpers import (
    PUBLISHED_RELEASE_RECORD,
    RecordingRunner,
    linux_stub_bin,
    load_installer,
    run_shim,
)
from public_installer_publication import (
    MISSING_VERSION,
    ReleaseOrigin,
    dry_run_installer,
    release_path,
    run_cli,
)
from test_public_installer import _options


@pytest.fixture
def origin():
    site = ReleaseOrigin()
    try:
        yield site
    finally:
        site.close()


def test_cli_dry_run_refuses_unpublished_explicit_version(origin, capsys) -> None:
    module = load_installer()
    code, out, err = run_cli(
        module,
        [
            "--yes",
            "--dry-run",
            "--no-setup",
            "--version",
            MISSING_VERSION,
            "--base-url",
            origin.base_url,
        ],
        capsys,
    )

    assert code == 1
    assert "Resolved Yoke" not in out
    assert "Install command" not in out
    assert "installer_release_unpublished" in err
    assert f"publish Yoke {MISSING_VERSION}" in err
    assert release_path(MISSING_VERSION) in origin.requested
    assert not any(path.startswith("/dist/channels/") for path in origin.requested)


def test_cli_dry_run_accepts_published_explicit_pin(origin, capsys) -> None:
    module = load_installer()
    origin.publish("1.2.3")

    code, out, err = run_cli(
        module,
        [
            "--yes",
            "--dry-run",
            "--no-setup",
            "--version",
            "1.2.3",
            "--base-url",
            origin.base_url,
        ],
        capsys,
    )

    assert code == 0, err
    assert err == ""
    assert "Resolved Yoke 1.2.3" in out
    assert "Install command:" in out
    assert "confirmed Yoke 1.2.3 is published" in out
    assert "No package was installed" in out
    assert "does not prove" in out


def test_cli_dry_run_encodes_the_version_path(origin, capsys) -> None:
    module = load_installer()
    version = "0.1.1+launch.591"
    origin.publish(version)

    code, out, err = run_cli(
        module,
        [
            "--yes",
            "--dry-run",
            "--no-setup",
            "--version",
            version,
            "--base-url",
            origin.base_url,
        ],
        capsys,
    )

    assert code == 0, err
    assert f"Resolved Yoke {version}" in out
    assert release_path(version) in origin.requested
    assert "%2B" in release_path(version)


def test_channel_pointer_to_unpublished_version_refuses(origin, capsys) -> None:
    module = load_installer()
    origin.channel("9.9.9")

    code, out, err = run_cli(
        module,
        ["--yes", "--dry-run", "--no-setup", "--base-url", origin.base_url],
        capsys,
    )

    assert code == 1
    assert "Resolved Yoke" not in out
    assert "installer_release_unpublished" in err
    assert "9.9.9" in err
    assert release_path("9.9.9") in origin.requested


def test_valid_channel_pin_succeeds(origin, capsys) -> None:
    module = load_installer()
    origin.channel("1.2.3")
    origin.publish("1.2.3")

    code, out, err = run_cli(
        module,
        ["--yes", "--dry-run", "--no-setup", "--base-url", origin.base_url],
        capsys,
    )

    assert code == 0, err
    assert "Resolved Yoke 1.2.3" in out
    assert "confirmed Yoke 1.2.3 is published" in out


def test_dry_run_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    module = load_installer()
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    installer, runner, output = dry_run_installer(
        module,
        fetcher=lambda _url: PUBLISHED_RELEASE_RECORD,
        version="1.2.3",
        base_url="https://origin.example",
    )

    installer.run()

    assert "Resolved Yoke 1.2.3" in output.getvalue()
    assert runner.commands == []
    assert not config_path.exists()


def test_install_does_not_fetch_a_release_record() -> None:
    module = load_installer()
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        raise AssertionError(url)

    installer = module.Installer(
        _options(
            module,
            version="1.2.3",
            yes=True,
            no_setup=True,
            dry_run=False,
            base_url="https://origin.example",
        ),
        fetcher=fetch,
        runner=RecordingRunner(),
        stdout=io.StringIO(),
        which=lambda _name: "/bin/yoke",
    )

    try:
        installer.run()
    except module.InstallError as exc:
        assert "installer_release" not in str(exc)
    assert calls == []


def test_dry_run_help_names_publication(capsys) -> None:
    module = load_installer()
    with pytest.raises(SystemExit) as raised:
        module.parse_args(["--help"])
    assert raised.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "published at the installer origin" in help_text
    assert "not proof the install would succeed" in help_text


def test_shim_help_names_publication(tmp_path: Path) -> None:
    result = run_shim(linux_stub_bin(tmp_path), args=("--help",))
    assert result.returncode == 0, result.stderr
    assert "published at this origin" in result.stdout
    assert "not proof the install would succeed" in result.stdout
