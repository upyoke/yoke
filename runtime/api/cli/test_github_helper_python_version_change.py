"""Checkout helpers survive a release that changes the Python minor version."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

import pytest

from runtime.api.cli.github_stable_helper_test_support import (
    run_git,
    write_github_app_config,
)
from runtime.api.cli.test_github_git_credential_install import _configured_repo
from runtime.api.cli.test_github_stable_helper_runtime import (
    _write_refresh_sitecustomize,
)
from yoke_cli.commands.adapters import github_credential_helper
from yoke_cli.config import github_git_credentials as credentials
from yoke_cli.config import github_project_setup, self_update
from yoke_cli.config import github_repo_helper_reconnect as reconnect

KEY = credentials.GITHUB_CREDENTIAL_HELPER_KEY
FILL = "protocol=https\nhost=github.com\n\n"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    repo, config, credential = _configured_repo(tmp_path, monkeypatch)
    write_github_app_config(config, credential, "release-test-token")
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connection_projects"] = {
        "local": [{"checkout": str(repo), "project_id": 1}]
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    run_git(repo, "remote", "add", "origin", "https://github.com/octo/repo.git")
    hooks = tmp_path / "python-hooks"
    _write_refresh_sitecustomize(hooks, "release-test-token")
    monkeypatch.setenv("PYTHONPATH", str(hooks))
    return repo, config, tmp_path / "yoke-cli-releases"


def _switch_release(monkeypatch, root: Path, name: str, minor: str) -> Path:
    """Publish a release generation and point ``current`` at it."""
    environment = root / "releases" / name / "tools" / "yoke-cli"
    python = environment / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.symlink_to(Path(sys.executable))
    (environment / "lib" / f"python3.{minor}" / "site-packages").mkdir(parents=True)
    current = root / "current"
    if current.is_symlink():
        current.unlink()
    current.symlink_to(environment.parent.parent, target_is_directory=True)
    monkeypatch.setattr(credentials.sys, "executable", str(python))
    monkeypatch.setattr(credentials.sys, "prefix", str(environment))
    return environment


def _orphaned_value(root: Path, config: Path) -> str:
    environment = root / "current" / "tools" / "yoke-cli"
    helper = (
        environment / "lib/python3.11/site-packages" / credentials.STABLE_HELPER_FILE_NAME
    )
    return f"!{environment / 'bin/python3'} {helper} --config {config}"


def _expected(config: Path) -> str:
    return credentials.helper_command(
        config_path=config,
        helper_path=credentials._helper_dir() / credentials.STABLE_HELPER_FILE_NAME,
    )


def test_saved_helper_path_survives_a_python_minor_change(machine, monkeypatch):
    repo, config, root = machine
    _switch_release(monkeypatch, root, "py311", "11")
    credentials.configure_repo_helper(repo, config_path=config)
    command = run_git(repo, "config", "--get", KEY).strip()

    _switch_release(monkeypatch, root, "py312", "12")
    # The installer's last step republishes the bundle in the new release.
    assert reconnect.restore_missing_bundle(config)["repaired"] is True

    helper = Path(shlex.split(command[1:])[1])
    assert "lib" not in helper.parts
    assert helper.is_file()
    assert run_git(repo, "config", "--get", KEY).strip() == command
    assert "password=release-test-token" in run_git(
        repo, "credential", "fill", input_text=FILL
    )


def _project_install(repo: Path, config: Path) -> None:
    github_project_setup.converge(repo, config_path=config)


def _refresh(_repo: Path, config: Path) -> None:
    assert (
        github_credential_helper.github_credential_helper_refresh(
            ["--config", str(config), "--json"]
        )
        == 0
    )


def _self_update(repo: Path, config: Path, monkeypatch) -> None:
    """Drive the already-current ``yoke update`` path against ``config``."""
    monkeypatch.setattr(
        self_update.install_binding,
        "require_packaged_install",
        lambda _command: {"version": "1.0"},
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _name: "/bin/yoke")
    target = SimpleNamespace(version="1.0", channel="stable", base_url="https://x")
    monkeypatch.setattr(self_update, "resolve_target", lambda **_kwargs: target)
    restore = reconnect.restore_missing_bundle
    monkeypatch.setattr(
        self_update.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config: restore(config),
    )
    monkeypatch.setattr(self_update, "_with_project_refresh", lambda _bin, r: r)
    result = self_update.run_update()
    assert result["credential_helper_rewritten"] == [str(repo)]


@pytest.mark.parametrize("entry", ["project_install", "refresh", "self_update"])
def test_orphaned_release_helper_is_rewritten(machine, monkeypatch, entry):
    repo, config, root = machine
    _switch_release(monkeypatch, root, "py312", "12")
    run_git(repo, "config", "--add", KEY, "")
    run_git(repo, "config", "--add", KEY, _orphaned_value(root, config))

    if entry == "project_install":
        _project_install(repo, config)
    elif entry == "refresh":
        _refresh(repo, config)
    else:
        _self_update(repo, config, monkeypatch)

    expected = _expected(config)
    assert run_git(repo, "config", "--get-all", KEY).splitlines() == ["", expected]
    assert "password=release-test-token" in run_git(
        repo, "credential", "fill", input_text=FILL
    )


def _refused_values(root: Path, config: Path) -> dict[str, str]:
    current = root / "current" / "tools" / "yoke-cli"
    python = current / "bin/python3"
    name = credentials.STABLE_HELPER_FILE_NAME
    helper = current / "lib/python3.11/site-packages" / name
    outside = root.parent / "elsewhere" / name
    dotted = f"{current}/../../current/tools/yoke-cli/lib/{name}"
    return {
        "wrong-config": f"!{python} {helper} --config {config}.other",
        "outside-root": f"!{python} {outside} --config {config}",
        "dot-dot": f"!{python} {dotted} --config {config}",
        "five-args": f"!{python} {helper} --config {config} extra",
        "other-name": f"!{python} {helper.with_name('other.py')} --config {config}",
        "editable": f"!{python} {helper} --config {config}",
    }


@pytest.mark.parametrize(
    "case",
    ["wrong-config", "outside-root", "dot-dot", "five-args", "other-name", "editable"],
)
def test_unverified_helper_is_left_untouched(machine, monkeypatch, tmp_path, case):
    repo, config, root = machine
    _switch_release(monkeypatch, root, "py312", "12")
    value = _refused_values(root, config)[case]
    if case == "editable":
        editable = tmp_path / "venv"
        monkeypatch.setattr(credentials.sys, "executable", str(editable / "bin/python"))
        monkeypatch.setattr(credentials.sys, "prefix", str(editable))
    run_git(repo, "config", "--add", KEY, value)
    before = (repo / ".git/config").read_bytes()

    result = reconnect.restore_missing_bundle(config)
    expected_configured = False if case == "other-name" else None
    assert result["configured"] is expected_configured
    with pytest.raises(github_project_setup.GitHubProjectSetupError, match="user-managed"):
        github_project_setup.converge(repo, config_path=config)

    assert (repo / ".git/config").read_bytes() == before
