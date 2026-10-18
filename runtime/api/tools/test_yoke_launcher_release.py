"""Real-process isolation and refusals for the operator launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from yoke_cli.config import install_binding, cli_release_runtime
from yoke_contracts import install_binding as contract_binding
from yoke_core.tools.install_yoke_launcher_core import write_launcher


@pytest.fixture
def released_launcher(tmp_path):
    tools = tmp_path / "tools"
    root = tools / "yoke-cli-releases"
    generation = root / "releases" / "1.2.3"
    environment = generation / "tools" / "yoke-cli"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment)],
        check=True,
        capture_output=True,
    )
    site = next((environment / "lib").glob("python*/site-packages"))
    cli = site / "yoke_cli"
    (cli / "config").mkdir(parents=True)
    (cli / "__init__.py").write_text("")
    (cli / "config" / "__init__.py").write_text("")
    shutil.copyfile(install_binding.__file__, cli / "config" / "install_binding.py")
    contracts = site / "yoke_contracts"
    contracts.mkdir()
    (contracts / "__init__.py").write_text("")
    shutil.copyfile(contract_binding.__file__, contracts / "install_binding.py")
    (contracts / "engine_version.py").write_text(
        'CLIENT_DISTRIBUTION_NAME = "yoke-cli"\n'
    )
    metadata = site / "yoke_cli-1.2.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: yoke-cli\nVersion: 1.2.3\n"
    )
    (metadata / "RECORD").write_text("yoke_cli/__init__.py,,\n")
    (cli / "main.py").write_text(
        "import json, sys\n"
        "def main(argv):\n"
        "    print(json.dumps({'argv': argv, 'origin': __file__, 'prefix': sys.prefix}))\n"
        "    return 7 if '--exit-seven' in argv else 0\n"
    )
    (generation / "lease").touch()
    (root / "current").symlink_to(generation)
    (root / "launcher").write_text(
        f"#!{sys._base_executable}\n"
        + Path(cli_release_runtime.__file__)
        .read_text()
        .replace("INSTALL_ROOT = None", f"INSTALL_ROOT = {str(root)!r}", 1)
    )
    (root / "launcher").chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(f"#!/bin/sh\nprintf '%s\\n' '{tools}'\n")
    uv.chmod(0o755)
    launcher = bindir / "yoke"
    write_launcher(launcher)
    env = dict(os.environ)
    env.pop("YOKE_SOURCE_DEV", None)
    env.pop("PYTHONHOME", None)
    env["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]
    return launcher, env, site, environment


def test_release_ignores_checkout_and_pythonpath_and_preserves_argv(
    released_launcher, tmp_path
):
    launcher, env, site, environment = released_launcher
    source = tmp_path / "source"
    package = source / "yoke_cli"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise RuntimeError('unreleased import')\n")
    env["PYTHONPATH"] = str(source)
    env["YOKE_HOME"] = str(source)
    result = subprocess.run(
        [
            str(launcher),
            "--env",
            "prod",
            "fleet",
            "argument with spaces",
            "--exit-seven",
        ],
        env=env,
        cwd=source,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 7, result.stderr
    output = json.loads(result.stdout)
    assert output["argv"] == [
        "--env",
        "prod",
        "fleet",
        "argument with spaces",
        "--exit-seven",
    ]
    assert output["origin"] == str(site / "yoke_cli" / "main.py")
    assert output["prefix"] == str(environment)


def test_missing_release_refuses_without_importing_source(released_launcher):
    launcher, env, site, environment = released_launcher
    (environment / "bin" / "python3").unlink()
    result = subprocess.run(
        [str(launcher), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "cli_release_unavailable" in result.stderr
    assert "public installer" in result.stderr
    assert "Traceback" not in result.stderr


def test_unversioned_tool_refuses(released_launcher):
    launcher, env, site, environment = released_launcher
    (site / "yoke_cli-1.2.3.dist-info" / "RECORD").unlink()
    result = subprocess.run(
        [str(launcher), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "released_cli_required" in result.stderr
    assert not result.stdout


def test_editable_tool_refuses(released_launcher, tmp_path):
    launcher, env, site, environment = released_launcher
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('name = "yoke"\n')
    (source / "runtime" / "harness").mkdir(parents=True)
    cli = source / "packages" / "yoke-cli" / "src" / "yoke_cli"
    shutil.copytree(site / "yoke_cli", cli)
    (site / "editable.pth").write_text(
        f"import sys; sys.path.insert(0, {str(cli.parent)!r})\n"
    )
    result = subprocess.run(
        [str(launcher), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "released_cli_required" in result.stderr
    assert not result.stdout


def test_source_requires_explicit_opt_in(released_launcher, tmp_path):
    launcher, env, site, environment = released_launcher
    source = tmp_path / "source"
    cli = source / "packages" / "yoke-cli" / "src" / "yoke_cli"
    cli.mkdir(parents=True)
    (cli / "__init__.py").write_text("")
    (cli / "main.py").write_text(
        "def main(argv):\n    print('source opt-in')\n    return 0\n"
    )
    env["YOKE_HOME"] = str(source)
    env["YOKE_SOURCE_DEV"] = "1"
    result = subprocess.run(
        [str(launcher), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "source opt-in"
    assert "explicit operator opt-in" in result.stderr


def test_source_opt_in_refuses_missing_checkout(released_launcher, tmp_path):
    launcher, env, site, environment = released_launcher
    env["YOKE_HOME"] = str(tmp_path / "missing")
    env["YOKE_SOURCE_DEV"] = "1"
    result = subprocess.run(
        [str(launcher), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "source_cli_unavailable" in result.stderr
    assert "unset YOKE_SOURCE_DEV" in result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout
