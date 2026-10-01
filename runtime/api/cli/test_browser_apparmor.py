"""Exact Chromium attachments, update replacement, and fail-closed provisioning."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import browser_apparmor as aa


@pytest.fixture
def setup(tmp_path, monkeypatch):
    restriction = tmp_path / "restriction"
    restriction.write_text("1\n")
    loaded = tmp_path / "profiles"
    loaded.write_text("")
    directory = tmp_path / "apparmor.d"
    directory.mkdir()
    monkeypatch.setattr(aa, "RESTRICTION", restriction)
    monkeypatch.setattr(aa, "PROFILES", loaded)
    monkeypatch.setattr(aa, "PROFILE_DIRECTORY", directory)
    monkeypatch.setattr(aa.sys, "platform", "linux")
    monkeypatch.setattr(aa.shutil, "which", lambda name: "/usr/sbin/" + name)
    monkeypatch.setattr(
        aa, "command_authority", lambda reason: (["sudo", "-n", "--"], False)
    )
    executables = [
        str(tmp_path / "chromium/chrome"),
        str(tmp_path / "headless/chrome-headless-shell"),
    ]
    commands, logs = [], []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if "-e" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(executables), "")
        destination, content, _ = command[-3:]
        aa.Path(destination).write_text(content)
        names = [
            line.split()[1]
            for line in content.splitlines()
            if line.startswith("profile ")
        ]
        loaded.write_text("\n".join(f"{name} (unconfined)" for name in names))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(aa.subprocess, "run", run)

    def ensure(**kwargs):
        aa.ensure_chromium_apparmor(
            tmp_path / "browser",
            SimpleNamespace(node="/node"),
            env={"PATH": "/test"},
            emit=logs.append,
            **kwargs,
        )

    return SimpleNamespace(
        ensure=ensure,
        commands=commands,
        logs=logs,
        executables=executables,
        restriction=restriction,
        loaded=loaded,
        directory=directory,
        run=run,
    )


@pytest.mark.parametrize("value", ["0\n", None])
def test_unrestricted_hosts_need_no_profile_or_authority(setup, value):
    if value is None:
        setup.restriction.unlink()
    else:
        setup.restriction.write_text(value)
    setup.ensure()
    assert setup.commands == []


def test_install_exact_paths_and_skip_already_loaded_profile(setup):
    setup.ensure()
    command, kwargs = setup.commands[-1]
    assert command[:3] == ["sudo", "-n", "--"]
    assert kwargs["capture_output"] is True
    content = command[-2]
    assert content.count("  userns,") == 2
    for path in setup.executables:
        assert f'"{path}" flags=(unconfined)' in content
    assert "*" not in content
    setup.ensure()
    assert len(setup.commands) == 3  # only a path probe on the second startup
    assert "already loaded" in setup.logs[-1]


def test_browser_update_replaces_old_attachments_in_same_profile(setup):
    setup.ensure()
    destination = setup.commands[-1][0][-3]
    old_paths = list(setup.executables)
    setup.executables[:] = [path.replace("chrome", "new-chrome") for path in old_paths]
    setup.ensure()
    command = setup.commands[-1][0]
    assert command[-3] == destination
    assert all(f'"{path}"' not in command[-2] for path in old_paths)
    assert "-r" in aa.INSTALL_PROFILE


def test_file_alone_does_not_prove_loaded_kernel_profile(setup):
    setup.ensure()
    setup.loaded.write_text("")
    setup.ensure()
    assert len(setup.commands) == 4


def test_failed_profile_load_stops_setup_with_cause_and_recovery(setup, monkeypatch):
    monkeypatch.setattr(
        aa.subprocess,
        "run",
        lambda command, **kwargs: (
            setup.run(command, **kwargs)
            if "-e" in command
            else subprocess.CompletedProcess(command, 1, "", "parser rejected userns")
        ),
    )
    with pytest.raises(
        RuntimeError, match="browser_apparmor_setup_failed.*parser rejected userns"
    ) as failure:
        setup.ensure()
    assert "retry yoke qa browser setup" in str(failure.value)
    assert not any("verified" in log for log in setup.logs)


def test_parser_success_requires_loaded_kernel_profiles(setup, monkeypatch):
    monkeypatch.setattr(
        aa.subprocess,
        "run",
        lambda command, **kwargs: (
            setup.run(command, **kwargs)
            if "-e" in command
            else subprocess.CompletedProcess(command, 0, "", "")
        ),
    )
    with pytest.raises(RuntimeError, match="not loaded into the kernel"):
        setup.ensure()


def test_missing_authority_has_one_named_refusal(setup, monkeypatch):
    def refuse(reason):
        raise RuntimeError(reason)

    monkeypatch.setattr(aa, "command_authority", refuse)
    with pytest.raises(
        RuntimeError, match="AppArmor restricts Chromium user namespaces"
    ):
        setup.ensure()
    assert len(setup.commands) == 1


def test_autoinstall_disabled_refuses_required_profile(setup):
    with pytest.raises(RuntimeError, match="YOKE_BROWSER_AUTOINSTALL=0"):
        setup.ensure(autoinstall=False)
    assert len(setup.commands) == 1


@pytest.mark.parametrize("suffix", ["*/chrome", '"/chrome', "\n/chrome"])
def test_attachment_cannot_expand_or_inject_profile(setup, suffix):
    setup.executables[0] += suffix
    with pytest.raises(RuntimeError, match="exact AppArmor attachment"):
        setup.ensure()
    assert len(setup.commands) == 1
