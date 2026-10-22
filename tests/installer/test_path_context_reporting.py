"""Check, fix and verify expose real shell winners without a repair loop."""

import json
import shutil

import pytest

from yoke_cli.commands.adapters import path_doctor as cli
from yoke_cli.config import path_doctor as doctor
from yoke_cli.config.path_state_contract import shell_setup_files


@pytest.fixture
def shell_home(tmp_path, monkeypatch):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    bindir = tmp_path / "tools with spaces"
    bindir.mkdir()
    launcher = bindir / "yoke"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    env = {
        "HOME": str(tmp_path), "PATH": f"{bindir}:/usr/bin:/bin",
        "SHELL": bash, "UV_TOOL_BIN_DIR": str(bindir),
    }
    monkeypatch.setattr(doctor, "SUPPORTED_SHELLS", ("bash",))
    diagnose = doctor.diagnose
    update = doctor.update_shell
    monkeypatch.setattr(doctor, "diagnose", lambda: diagnose(env=env))
    monkeypatch.setattr(doctor, "update_shell", lambda: update(env=env))
    doctor.update_shell()
    return tmp_path, env, launcher


def test_clean_contexts_show_winner_and_expected_in_every_command(shell_home, capsys):
    _, _, launcher = shell_home
    for command, args in ((cli.path_check, []), (cli.path_fix, ["--yes"]),
                          (cli.path_verify, [])):
        assert command(args) == 0
        output = capsys.readouterr().out
        for context in ("login", "interactive", "non-login", "ssh"):
            assert (f"bash {context}: ok; yoke -> {launcher}; "
                    f"expected {launcher}") in output


def test_late_override_survives_repair_until_manual_correction(shell_home, capsys):
    home, env, launcher = shell_home
    old = home / "oldtools"
    old.mkdir()
    competing = old / "yoke"
    competing.write_text("#!/bin/sh\nexit 7\n")
    competing.chmod(0o755)
    rc = home / ".bashrc"
    owned = rc.read_text()
    # The interactive-only override leaves login and SSH probes correct.
    override = f'case $- in *i*) export PATH="{old}:$PATH" ;; esac\n'
    rc.write_text(owned + override)
    before = {file: file.read_bytes() for file in shell_setup_files(env)}
    original_launcher = launcher.read_bytes()
    original_competing = competing.read_bytes()
    diagnosis = doctor.diagnose()
    assert diagnosis.needs_fix
    assert not diagnosis.login_needs_fix
    assert not diagnosis.ssh_needs_fix
    assert diagnosis.yoke_shadowed_by == ""
    interactive = next(row for row in diagnosis.contexts
                       if row["context"] == "interactive")
    assert interactive["resolved"]["yoke"] == str(competing)
    assert interactive["reason"] == "shell_path_shadowed"
    assert str(rc) in interactive["recovery"]
    assert str(old) in interactive["recovery"]
    assert "comes first" in interactive["recovery"]
    assert "yoke path fix" not in interactive["recovery"]

    for command, args in ((cli.path_check, []), (cli.path_fix, ["--yes"]),
                          (cli.path_fix, ["--yes"]), (cli.path_verify, [])):
        assert command(args) == 1
        output = capsys.readouterr().out
        assert f"bash login: ok; yoke -> {launcher}" in output
        assert (f"bash interactive: shell_path_shadowed; yoke -> {competing}; "
                f"expected {launcher}") in output
        assert str(rc) in output
        if command != cli.path_check:
            assert "yoke path fix --yes" not in output
        assert "PATH verified." not in output

    for command, args in ((cli.path_check, ["--json"]),
                          (cli.path_fix, ["--yes", "--json"]),
                          (cli.path_verify, ["--json"])):
        assert command(args) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["contexts"] == list(diagnosis.contexts)
    assert before == {file: file.read_bytes() for file in shell_setup_files(env)}
    assert launcher.read_bytes() == original_launcher
    assert competing.read_bytes() == original_competing
    # The user's correction removes only their competing PATH statement.
    rc.write_text(owned)
    assert cli.path_verify([]) == 0
    assert "shell_path_shadowed" not in capsys.readouterr().out


def test_missing_owned_block_is_repaired_and_repeat_is_idempotent(shell_home, capsys):
    home, env, launcher = shell_home
    rc = home / ".bashrc"
    user = "# unrelated user settings\nexport USER_SETTING=yes\n"
    rc.write_text(user)
    assert cli.path_check([]) == 1
    capsys.readouterr()
    assert cli.path_fix(["--yes"]) == 0
    assert "PATH verified." in capsys.readouterr().out
    assert rc.read_text().endswith(user)
    before = {file: file.read_bytes() for file in shell_setup_files(env)}
    assert cli.path_fix(["--yes"]) == 0
    capsys.readouterr()
    assert before == {file: file.read_bytes() for file in shell_setup_files(env)}
    assert launcher.exists()


def test_different_winner_fails_even_when_canonical_launcher_is_missing(tmp_path):
    preferred = tmp_path / "bin"
    assert doctor._shadowing_yoke_path(
        [doctor.ToolResolution("yoke", "/other/bin/yoke")], bindir=str(preferred),
    ) == "/other/bin/yoke"


@pytest.mark.parametrize("shell,context,settings", [
    ("bash", "interactive", ".bashrc"),
    ("bash", "login", ".profile"),
    ("bash", "non-login", "user-env"),
    ("zsh", "interactive", "zsh/.zshrc"),
    ("fish", "ssh", "config/fish/config.fish"),
])
def test_manual_recovery_names_context_startup_files(tmp_path, shell, context, settings):
    from yoke_cli.config.path_shell_contexts import _recovery

    env = {"HOME": str(tmp_path), "ZDOTDIR": str(tmp_path / "zsh"),
           "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "BASH_ENV": str(tmp_path / "user-env")}
    recovery = _recovery(shell, context, env, "/old/yoke", "/canonical/yoke", "")
    assert str(tmp_path / settings) in recovery
    assert "line " not in recovery
    assert "yoke path fix" not in recovery


def test_setup_failure_reports_remaining_context_without_repair_loop(shell_home, monkeypatch):
    from yoke_cli.config import onboard_apply_path
    from yoke_cli.config.onboard_wizard_path import PathFlow

    home, _, _ = shell_home
    old = home / "oldtools"
    old.mkdir()
    yoke = old / "yoke"
    yoke.write_text("#!/bin/sh\nexit 0\n")
    yoke.chmod(0o755)
    rc = home / ".bashrc"
    with rc.open("a") as stream:
        stream.write(f'case $- in *i*) export PATH="{old}:$PATH" ;; esac\n')

    def apply(plan, *, progress, report):
        report["path_repair"] = {
            **plan, "login_verified": False,
            "login_resolved": {tool: "/canonical/" + tool for tool in doctor.TOOLS},
            "contexts": list(doctor.diagnose().contexts),
        }

    monkeypatch.setattr(onboard_apply_path, "apply", apply)
    _, error = PathFlow()._check_install()
    assert "bash interactive: shell_path_shadowed" in error
    assert str(yoke) in error
    assert str(rc) in error
    assert "yoke path fix" not in error
