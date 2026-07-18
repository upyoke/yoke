"""Public installer failure messaging and product-boundary audits."""

import io
import json
import subprocess
from pathlib import Path

from public_installer_helpers import RecordingRunner, load_installer


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


def test_public_index_failure_names_both_owned_sources(tmp_path: Path) -> None:
    installer_mod = load_installer()
    output = io.StringIO()
    runner = RecordingRunner(
        rc=1,
        stderr="connection refused: https://pypi.org/simple/pydantic/",
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="1.2.3"),
        runner=runner,
        stdout=output,
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected public index failure")

    assert "configured Yoke package index and public PyPI" in message
    assert "https://pypi.org/simple/pydantic/" in message
    assert "Couldn't install Yoke" in output.getvalue()


def test_channel_missing_version_pin_fails(tmp_path: Path) -> None:
    installer_mod = load_installer()
    channels_dir = tmp_path / "site" / "dist" / "channels"
    channels_dir.mkdir(parents=True)
    (channels_dir / "stable.json").write_text("{}", encoding="utf-8")
    installer = installer_mod.Installer(
        _options(
            installer_mod,
            base_url=tmp_path.joinpath("site").as_uri(),
            dry_run=True,
        ),
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        assert "missing a version pin" in str(exc)
    else:
        raise AssertionError("expected missing version pin failure")


def test_product_boundary_audit_accepts_installed_engine() -> None:
    # Every lockstep product distribution ships on the machine. The audit also
    # rejects a client wielding source-dev/admin authority.
    installer_mod = load_installer()
    package_versions = {
        package: "1.2.3"
        for package in (
            installer_mod.PRODUCT_PACKAGE,
            *installer_mod.LOCKSTEP_PRODUCT_PACKAGES,
        )
    }
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps(
            {
                "runtime": {
                    "imports": {"yoke_core": {"available": True}},
                    "package_versions": package_versions,
                },
                "connection": {"client_authority": "api"},
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(_options(installer_mod), runner=runner)

    installer._product_boundary_audit()

    assert runner.commands == [["yoke", "status", "--json"]]


def test_product_boundary_audit_rejects_source_dev_authority() -> None:
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps(
            {
                "runtime": {
                    "package_versions": {
                        package: "1.2.3"
                        for package in (
                            "yoke-cli",
                            "yoke-contracts",
                            "yoke-harness",
                            "yoke-core",
                        )
                    },
                },
                "connection": {"client_authority": "source-dev/admin"},
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(_options(installer_mod), runner=runner)

    try:
        installer._product_boundary_audit()
    except installer_mod.InstallError as exc:
        assert "product-boundary audit failed" in str(exc)
        assert "source-dev/admin" in str(exc)
    else:
        raise AssertionError("expected product-boundary audit failure")


def test_advise_path_points_at_yoke_path_fix() -> None:
    installer_mod = load_installer()
    output = io.StringIO()
    installer = installer_mod.Installer(
        _options(installer_mod),
        which=lambda name: None,
        stdout=output,
    )

    installer._advise_path()

    assert "yoke path fix" in output.getvalue()
