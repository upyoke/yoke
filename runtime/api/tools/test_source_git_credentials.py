"""Exercise source credential isolation through Git's real helper protocol."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_contracts.git_credential_command import helper_command, rebind_helper
from yoke_core.tools.source_git_credentials import snapshot_git_helpers
from yoke_core.tools.source_machine_home import isolated_machine_home


def _git(env, *args, input=None):
    return subprocess.run(
        ["git", *args],
        env=env,
        input=input,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


@pytest.fixture
def repository(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_CONFIG")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(tmp_path / "global"),
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="false",
        YOKE_SESSION_ID="fixture-session",
    )
    monkeypatch.chdir(repo)
    _git(env, "init", "--quiet")
    home = tmp_path / "machine home"
    secret = home / "secrets" / "token"
    secret.parent.mkdir(parents=True)
    secret.write_text("fixture-password")
    config = home / "config.json"
    config.write_text(json.dumps({"credential": str(secret)}))
    env["YOKE_MACHINE_HOME"] = str(home)
    helper = tmp_path / "credential helper.py"
    helper.write_text(
        "import json, os, pathlib, sys\n"
        "if sys.argv[-1] != 'get': sys.exit(0)\n"
        "config = pathlib.Path(sys.argv[2])\n"
        "assert config.parent == pathlib.Path(os.environ['YOKE_MACHINE_HOME'])\n"
        "secret = pathlib.Path(json.loads(config.read_text())['credential'])\n"
        "assert secret.is_relative_to(config.parent / 'secrets')\n"
        "print('password=' + secret.read_text())\n"
        "secret.write_text('child-write')\n"
    )
    command = helper_command(Path(sys.executable), helper, config)
    _git(env, "config", "--add", "credential.https://github.com.helper", command)
    return repo, env, config, secret, command


def test_snapshot_git_fill_keeps_helper_order_and_parent_files(repository):
    repo, env, config, secret, command = repository
    # Earlier matching helpers are cleared by the existing URL-scoped reset.
    _git(
        env, "config", "--global", "--add", "credential.helper", "!echo username=wrong"
    )
    _git(env, "config", "--unset-all", "credential.https://github.com.helper")
    for value in ("", "!echo username=fixture-user", command):
        _git(env, "config", "--add", "credential.https://github.com.helper", value)
    env.update(
        GIT_CONFIG_COUNT="2",
        GIT_CONFIG_KEY_0="color.ui",
        GIT_CONFIG_VALUE_0="false",
        GIT_CONFIG_KEY_1="credential.https://elsewhere.invalid.helper",
        GIT_CONFIG_VALUE_1="!echo password=unrelated",
    )
    files = [config, secret, repo / ".git" / "config", Path(env["GIT_CONFIG_GLOBAL"])]
    before = {path: path.read_bytes() for path in files}
    parent_env = dict(env)
    with isolated_machine_home(env) as child:
        output = _git(
            child, "credential", "fill", input="protocol=https\nhost=github.com\n\n"
        )
        assert "username=fixture-user" in output
        assert "password=fixture-password" in output
        assert _git(child, "config", "--get", "color.ui").strip() == "false"
        assert (
            _git(
                child,
                "config",
                "--get-urlmatch",
                "credential.helper",
                "https://elsewhere.invalid",
            )
            .strip()
            .endswith("password=unrelated")
        )
        assert (
            Path(child["YOKE_MACHINE_HOME"]) / "secrets" / "token"
        ).read_text() == "child-write"
    assert env == parent_env
    assert {path: path.read_bytes() for path in files} == before


def test_real_home_opt_in_keeps_original_git_environment(repository):
    _, env, _, secret, _ = repository
    with isolated_machine_home(env, allow_real=True) as child:
        assert child == env
        # Supply username without replacing the configured password helper.
        output = _git(
            child,
            "-c",
            "credential.username=fixture-user",
            "credential",
            "fill",
            input="protocol=https\nhost=github.com\n\n",
        )
        assert "password=fixture-password" in output
    assert secret.read_text() == "child-write"


def test_unrelated_config_and_absent_helpers_leave_environment_intact(repository):
    _, env, config, _, _ = repository
    assert snapshot_git_helpers(env, config.parent / "other.json", config) == env
    _git(env, "config", "--unset-all", "credential.https://github.com.helper")
    assert snapshot_git_helpers(env, config, config.parent / "snapshot.json") == env


def test_git_command_line_environment_helpers_are_rebound(repository):
    _, env, _, _, command = repository

    def quote(value):
        return "'" + value.replace("'", "'\\''") + "'"

    env["GIT_CONFIG_PARAMETERS"] = " ".join(
        map(
            quote,
            [
                "color.ui=false",
                "credential.https://github.com.helper=",
                "credential.https://github.com.helper=!echo username=fixture-user",
                "credential.https://github.com.helper=" + command,
            ],
        )
    )
    with isolated_machine_home(env) as child:
        output = _git(
            child, "credential", "fill", input="protocol=https\nhost=github.com\n\n"
        )
        assert "password=fixture-password" in output
        assert _git(child, "config", "--get", "color.ui").strip() == "false"


@pytest.mark.parametrize(
    "value",
    [
        "manager",
        "!unterminated'",
        "!python helper --config /real/config.json",
        "!/python /helper --config /real/config.json; echo unsafe",
        "!/python /helper --config /other/config.json",
    ],
)
def test_noncanonical_or_unrelated_helper_is_unchanged(value):
    assert (
        rebind_helper(value, Path("/real/config.json"), Path("/copy/config.json"))
        == value
    )
