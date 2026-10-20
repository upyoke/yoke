"""Tests run against an isolated home, and a run that writes the real one fails."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

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


def test_the_guard_records_each_kind_of_real_home_write(tmp_path: Path):
    real = tmp_path / "real-home"
    guard = isolation.RealHomeWriteGuard(real, exempt=[real / "checkout"])
    guard.start()
    guard.audit("open", (str(real / ".claude/settings.json"), "w", 0))
    guard.audit("open", (str(real / ".cursor/cli-config.json"), None, os.O_WRONLY))
    guard.audit(
        "os.rename", (str(tmp_path / "x.tmp"), str(real / ".codex/config.toml"))
    )
    guard.audit("os.mkdir", (str(real / ".codex/rules"), 0o777, None))
    guard.audit("open", (str(real / ".gitconfig"), "r", 0))
    guard.audit("open", (str(real / "checkout/conftest.py"), "w", 0))
    guard.audit("os.remove", (3, None))
    assert guard.stop() == [
        ("open", str(real / ".claude/settings.json")),
        ("open", str(real / ".cursor/cli-config.json")),
        ("os.rename", str(real / ".codex/config.toml")),
        ("os.mkdir", str(real / ".codex/rules")),
    ]


def test_the_guard_is_quiet_outside_a_test(tmp_path: Path):
    guard = isolation.RealHomeWriteGuard(tmp_path)
    guard.audit("open", (str(tmp_path / "f"), "w", 0))
    assert guard.writes == []


def test_the_installed_guard_sees_a_real_write_this_process_makes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A path captured before HOME moved still reaches the real home: caught."""
    real = tmp_path / "real-home"
    real.mkdir()
    monkeypatch.setattr(isolation.GUARD, "home", str(real))
    captured_at_import = real / ".claude" / "settings.json"
    captured_at_import.parent.mkdir()
    captured_at_import.write_text("{}\n")
    seen = list(isolation.GUARD.writes)
    isolation.GUARD.writes.clear()
    assert ("os.mkdir", str(captured_at_import.parent)) in seen
    assert ("open", str(captured_at_import)) in seen


def test_the_violation_names_every_path_and_the_fix():
    message = isolation.real_home_violation(
        [("open", "/home/dev/.claude/settings.json")] * 2
    )
    assert message.startswith("real_home_written:")
    assert message.count("/home/dev/.claude/settings.json") == 1
    assert "Resolve the path at call time" in message
