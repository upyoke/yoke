"""Tests run against an isolated home, and a run that writes the real one fails."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime import real_home_isolation as isolation
from yoke_contracts import global_skill_install
from yoke_contracts import harness_unattended_posture as posture
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS


def test_every_home_resolver_lands_in_the_isolated_home(tmp_path: Path):
    home = isolation.isolated_home(tmp_path)
    resolved = [
        Path.home(),
        Path(os.path.expanduser("~")),
        global_skill_install.user_home(),
        posture.codex_config_path(),
        posture.cursor_config_path(),
        posture.claude_settings_path(),
        posture.claude_config_path(),
        *(spec.user_config_path() for spec in HARNESS_MACHINE_HOOKS.values()),
    ]
    assert os.environ["HOME"] == str(home)
    assert [path for path in resolved if not path.is_relative_to(home)] == []


def test_a_subprocess_inherits_the_isolated_home(tmp_path: Path):
    child = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert child.stdout.strip() == str(isolation.isolated_home(tmp_path))


def test_an_unpatched_posture_pass_writes_only_the_isolated_home(tmp_path: Path):
    """The machine-wide pass, with no path patched, stays inside ``tmp_path``."""
    from yoke_contracts.harness_posture_install import (
        configure_harness_unattended_posture,
    )

    home = isolation.isolated_home(tmp_path)
    for spec in HARNESS_MACHINE_HOOKS.values():
        spec.home_path().mkdir(parents=True)
    posture.cursor_config_path().write_text("{}\n", encoding="utf-8")
    actions = configure_harness_unattended_posture(
        checkout=tmp_path / "checkout", stream=io.StringIO()
    )
    assert actions
    written = [
        posture.claude_settings_path(),
        posture.codex_config_path(),
        posture.cursor_config_path(),
    ]
    assert all(path.is_relative_to(home) and path.is_file() for path in written)
    assert json.loads(posture.cursor_config_path().read_text()) != {}


def _session() -> SimpleNamespace:
    config = SimpleNamespace(
        stash=pytest.Stash(),
        pluginmanager=SimpleNamespace(get_plugin=lambda name: None),
    )
    return SimpleNamespace(config=config, exitstatus=pytest.ExitCode.OK)


def test_a_run_that_writes_a_real_home_setup_file_fails(tmp_path, capsys):
    session = _session()
    isolation.pytest_sessionstart(session)
    settings = posture.claude_settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text('{"permissions": {"allow": ["Bash(yoke:*)"]}}\n')
    isolation.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    reported = capsys.readouterr().out
    assert "real_home_written" in reported
    assert str(settings) in reported


def test_a_run_that_leaves_the_real_home_alone_keeps_its_status(tmp_path):
    settings = posture.claude_settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n")
    session = _session()
    isolation.pytest_sessionstart(session)
    settings.write_text("{}\n")
    isolation.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.OK


def test_the_fingerprint_covers_every_setup_file():
    files = isolation.real_home_setup_files()
    assert posture.cursor_config_path() in files
    assert posture.claude_config_path() in files
    for spec in HARNESS_MACHINE_HOOKS.values():
        assert spec.user_config_path() in files
