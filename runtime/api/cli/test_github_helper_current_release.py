"""Checkout helpers follow CLI publication without retaining pruned releases."""

from pathlib import Path
import shlex
import shutil
import sys

from runtime.api.cli.cli_release_runtime_test_support import point_current
from runtime.api.cli.github_stable_helper_test_support import (
    run_git,
    write_github_app_config,
)
from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo,
)
from runtime.api.cli.github_stable_helper_runtime_test_support import (
    _write_refresh_sitecustomize,
)
from yoke_cli.config import github_git_credentials as credentials
from yoke_cli.config import github_repo_helper_reconnect as reconnect


def test_checkout_helper_survives_release_switch_and_prune(tmp_path, monkeypatch):
    repo, config, credential = _configured_repo(tmp_path, monkeypatch)
    write_github_app_config(config, credential, "release-test-token")
    root = tmp_path / "install with spaces" / "yoke-cli-releases"
    original_python = Path(sys.executable)

    def release(name):
        generation = root / "releases" / name
        environment = generation / "tools" / "yoke-cli"
        python = environment / "bin" / "python3"
        python.parent.mkdir(parents=True)
        python.symlink_to(original_python)
        point_current(root, generation)
        monkeypatch.setattr(credentials.sys, "executable", str(python))
        monkeypatch.setattr(credentials.sys, "prefix", str(environment))
        return generation

    old = release("old")
    report = credentials.configure_repo_helper(repo, config_path=config)
    command = run_git(repo, "config", "--get", report["key"]).strip()
    helper_dir = root / "github-credential-helper"
    assert shlex.split(command[1:]) == [
        str(root / "python"),
        str(helper_dir / credentials.STABLE_HELPER_FILE_NAME),
        "--config",
        str(config),
    ]

    release("new")
    shutil.rmtree(old)
    hooks = tmp_path / "python-hooks"
    _write_refresh_sitecustomize(hooks, "release-test-token")
    monkeypatch.setenv("PYTHONPATH", str(hooks))

    filled = run_git(
        repo, "credential", "fill", input_text="protocol=https\nhost=github.com\n\n"
    )
    assert "password=release-test-token" in filled
    assert reconnect._classify_helper_reference(repo, config_path=config) == "match"
    assert (
        credentials.configure_repo_helper(repo, config_path=config)["changed"] is False
    )
    assert run_git(repo, "config", "--get", report["key"]).strip() == command


def test_helper_command_preserves_non_release_runtime(tmp_path, monkeypatch):
    python = tmp_path / "venv" / "bin" / "python"
    helper = tmp_path / "site" / credentials.STABLE_HELPER_FILE_NAME
    config = tmp_path / "config.json"
    monkeypatch.setattr(credentials.sys, "executable", str(python))
    command = credentials.helper_command(config_path=config, helper_path=helper)
    assert shlex.split(command[1:]) == [
        str(python),
        str(helper),
        "--config",
        str(config),
    ]
