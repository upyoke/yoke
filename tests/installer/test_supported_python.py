"""Installer and CI agree on the supported Python endpoints."""

import io
import json
import subprocess

import pytest

from public_installer_helpers import RecordingRunner, load_installer, write_channel
from test_public_installer import _options
from yoke_core.tools import ci_shards
from packaging.specifiers import SpecifierSet

PYPI_INDEX = "https://pypi.org/simple/"


def test_install_command_uses_generated_index_config() -> None:
    installer_mod = load_installer()
    installer = installer_mod.Installer(_options(installer_mod))

    command = installer.install_command(
        "yoke-cli==1.2.3", config_path="/tmp/yoke-uv-index.toml"
    )

    assert command == [
        "uv",
        "tool",
        "install",
        "yoke-cli==1.2.3",
        "--python",
        installer_mod.PYTHON_CONSTRAINT,
        "--reinstall",
        "--force",
        "--with",
        "yoke-contracts==1.2.3",
        "--with",
        "yoke-harness==1.2.3",
        "--with",
        "yoke-core==1.2.3",
        "--default-index",
        PYPI_INDEX,
        "--index-strategy",
        "first-index",
        "--config-file",
        "/tmp/yoke-uv-index.toml",
    ]


def test_install_command_uses_only_supported_python() -> None:
    installer_mod = load_installer()
    command = installer_mod.Installer(_options(installer_mod)).install_command(
        "yoke-cli"
    )
    assert command[command.index("--python") + 1] == ">=3.10,<3.14"
    assert ci_shards.python_versions() == ["3.10", "3.13"]
    output = dict(line.split("=", 1) for line in ci_shards.fan_out_lines())
    assert json.loads(output["python_versions"]) == ci_shards.python_versions()


def test_dry_run_resolves_stable_channel_and_writes_nothing(tmp_path) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="1.2.3")
    output = io.StringIO()
    runner = RecordingRunner()
    installer = installer_mod.Installer(
        _options(installer_mod, dry_run=True, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: None,
        stdout=output,
    )

    installer.run()

    rendered = output.getvalue()
    assert "Resolved Yoke 1.2.3" in rendered
    assert "uv tool install yoke-cli==1.2.3" in rendered
    assert "--python '>=3.10,<3.14'" in rendered
    assert "--with yoke-contracts==1.2.3" in rendered
    assert "--with yoke-harness==1.2.3" in rendered
    assert "--with yoke-core==1.2.3" in rendered
    assert "--reinstall" in rendered
    assert "Dry run" in rendered
    assert runner.commands == []


@pytest.mark.parametrize("host_version", ["3.9", "3.14", "3.15"])
def test_unsupported_only_host_refuses_with_supported_range_and_recovery(host_version):
    module = load_installer()
    commands = []

    def runner(command):
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 1, "", f"Only Python {host_version} found"
        )

    installer = module.Installer(_options(module), runner=runner)
    with pytest.raises(
        module.InstallError, match="supported_python_unavailable"
    ) as failure:
        installer._run_uv_install(installer.install_command("yoke-cli"))
    assert commands == [
        ["uv", "python", "find", "--no-python-downloads", module.PYTHON_CONSTRAINT]
    ]
    assert "supports Python >=3.10,<3.14" in str(failure.value)
    assert "uv python install '>=3.10,<3.14'" in str(failure.value)
    assert "yoke update" in str(failure.value)


@pytest.mark.parametrize("host_version", ["3.10", "3.13"])
def test_supported_host_reaches_install(host_version):
    module = load_installer()
    runner = RecordingRunner(stdout=host_version)
    installer = module.Installer(_options(module), runner=runner)
    command = installer.install_command("yoke-cli")
    installer._run_uv_install(command)
    assert runner.commands[-1] == command


@pytest.mark.parametrize(
    "version,supported",
    [
        ("3.9", False),
        ("3.10", True),
        ("3.11", True),
        ("3.12", True),
        ("3.13.9", True),
        ("3.14", False),
        ("3.15", False),
    ],
)
def test_supported_range_boundaries(version, supported):
    assert (version in SpecifierSet(load_installer().PYTHON_CONSTRAINT)) is supported
