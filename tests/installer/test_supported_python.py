"""Installer and CI agree on the supported Python endpoints."""

import io
import json
import subprocess

import pytest

from public_installer_helpers import (
    RecordingRunner,
    current_os_answer,
    load_installer,
    write_channel,
    write_published_release,
)
from tests.installer.public_installer_test_support import _options
from yoke_core.tools import ci_shards
from packaging.specifiers import SpecifierSet

PYPI_INDEX = "https://pypi.org/simple/"
# Native Windows needs Python 3.12+ (install.py PYTHON_CONSTRAINT); CI's 3.11
# endpoint covers macOS/Linux.
CONSTRAINT = current_os_answer(posix=">=3.11,<3.15", windows=">=3.12,<3.15")


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
    assert command[command.index("--python") + 1] == CONSTRAINT
    assert ci_shards.python_versions() == ["3.11", "3.14"]
    output = dict(line.split("=", 1) for line in ci_shards.fan_out_lines())
    assert json.loads(output["python_versions"]) == ci_shards.python_versions()


def test_dry_run_resolves_stable_channel_and_writes_nothing(tmp_path) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="1.2.3")
    write_published_release(tmp_path, version="1.2.3")
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
    assert f"--python '{CONSTRAINT}'" in rendered
    assert "--with yoke-contracts==1.2.3" in rendered
    assert "--with yoke-harness==1.2.3" in rendered
    assert "--with yoke-core==1.2.3" in rendered
    assert "--reinstall" in rendered
    assert "confirmed Yoke 1.2.3 is published" in rendered
    assert "No package was installed" in rendered
    assert runner.commands == []


FIND = ["uv", "python", "find", "--no-project", "--show-version"]


def _runner(module, commands, *, find=(0, "3.12.16", ""), python_install=(0, "", ""), tool=(0, "", "")):
    finds = [find] if isinstance(find, tuple) else list(find)

    def runner(command):
        commands.append(command)
        if command[:5] == FIND:
            rc, out, err = finds.pop(0) if len(finds) > 1 else finds[0]
        elif command[:3] == ["uv", "python", "install"]:
            rc, out, err = python_install
        else:
            rc, out, err = tool
        return subprocess.CompletedProcess(command, rc, out, err)

    return runner


def test_tool_venv_names_the_exact_python_patch():
    # A minor request makes uv point the venv at its minor-version link, a
    # Windows junction OpenSSH sessions cannot follow (astral-sh/uv#19616).
    module = load_installer()
    commands = []
    installer = module.Installer(_options(module), runner=_runner(module, commands))
    command = installer.install_command("yoke-cli")
    installer._run_uv_install(command)
    assert commands[0] == [*FIND, module.PYTHON_CONSTRAINT]
    pinned = list(command)
    pinned[pinned.index("--python") + 1] = "3.12.16"
    assert commands[1:] == [pinned]


def test_missing_python_installs_managed_supported_python_before_pinning():
    module = load_installer()
    commands = []
    runner = _runner(module, commands, find=[(2, "", "No interpreter found"), (0, "3.14.2", "")])
    installer = module.Installer(_options(module), runner=runner)
    installer._run_uv_install(installer.install_command("yoke-cli"))
    assert commands[:3] == [
        [*FIND, module.PYTHON_CONSTRAINT],
        ["uv", "python", "install", module.PYTHON_CONSTRAINT],
        [*FIND, module.PYTHON_CONSTRAINT],
    ]
    assert commands[3][commands[3].index("--python") + 1] == "3.14.2"
    assert "--no-python-downloads" not in commands[3]


@pytest.mark.parametrize(
    "reason", ["Python download failed", "Python downloads disabled"]
)
def test_unavailable_python_names_recovery(reason):
    module = load_installer()
    commands = []
    runner = _runner(module, commands, find=(2, "", "none"), python_install=(1, "", reason))
    installer = module.Installer(_options(module), runner=runner)
    with pytest.raises(
        module.InstallError, match="supported_python_unavailable"
    ) as failure:
        installer._run_uv_install(installer.install_command("yoke-cli"))
    assert [c[:3] for c in commands] == [["uv", "python", "find"], ["uv", "python", "install"]]
    assert f"supports Python {CONSTRAINT}" in str(failure.value)
    assert f"uv python install '{CONSTRAINT}'" in str(failure.value)
    assert "yoke update" in str(failure.value)
    assert reason in str(failure.value)


def test_unnamed_python_patch_refuses_by_name():
    module = load_installer()
    runner = _runner(module, [], find=(0, "/usr/bin/python3", ""))
    installer = module.Installer(_options(module), runner=runner)
    with pytest.raises(module.InstallError, match="supported_python_unresolved"):
        installer._run_uv_install(installer.install_command("yoke-cli"))


UNTRUSTED = (
    "error: Failed to create Python minor version link directory\n"
    "  cause: The path cannot be traversed because it contains an untrusted "
    "mount point. (os error 448)"
)


@pytest.mark.parametrize("failing", ["python_install", "tool"])
def test_untrusted_mount_point_refuses_by_name(monkeypatch, failing):
    module = load_installer()
    monkeypatch.setattr(module.sys, "platform", "win32")
    steps = {"python_install": (1, "", UNTRUSTED)} if failing == "python_install" else {"tool": (2, "", UNTRUSTED)}
    find = (2, "", "none") if failing == "python_install" else (0, "3.12.16", "")
    installer = module.Installer(_options(module), runner=_runner(module, [], find=find, **steps))
    with pytest.raises(module.InstallError) as failure:
        installer._run_uv_install(installer.install_command("yoke-cli"))
    message = str(failure.value)
    assert message.startswith("windows_untrusted_mount_point:")
    assert "https://github.com/astral-sh/uv/issues/19616" in message
    assert "local PowerShell" in message
    assert "supported_python_unavailable" not in message
    assert "Failed to create Python minor version link" not in message


def test_package_install_failure_keeps_package_diagnostic():
    module = load_installer()
    installer = module.Installer(
        _options(module),
        runner=RecordingRunner(rc=1, stderr="No package found"),
    )
    with pytest.raises(module.InstallError) as failure:
        installer._run_uv_install(installer.install_command("yoke-cli"))
    assert "No package found" in str(failure.value)
    assert "supported_python_unavailable" not in str(failure.value)


@pytest.mark.parametrize(
    "version,supported",
    [
        ("3.9", False),
        ("3.10", False),
        ("3.11", current_os_answer(posix=True, windows=False)),
        ("3.12", True),
        ("3.13.9", True),
        ("3.14", True),
        ("3.15", False),
    ],
)
def test_supported_range_boundaries(version, supported):
    assert (version in SpecifierSet(load_installer().PYTHON_CONSTRAINT)) is supported


def test_install_proof_refuses_tool_environments_on_the_minor_link(tmp_path):
    from runtime.api.tools.prove_public_installer import assert_patch_python_homes

    venv = tmp_path / "releases/1.0/tools/yoke-cli"
    venv.mkdir(parents=True)
    config = venv / "pyvenv.cfg"
    config.write_text(
        "home = C:\\uv\\python\\cpython-3.12.16-windows-x86_64-none\n", encoding="utf-8"
    )
    assert_patch_python_homes(tmp_path)
    config.write_text(
        "home = C:\\uv\\python\\cpython-3.12-windows-x86_64-none\n", encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="minor-version link"):
        assert_patch_python_homes(tmp_path)
