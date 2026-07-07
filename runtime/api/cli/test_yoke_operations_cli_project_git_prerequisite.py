"""Git prerequisite install guidance for project onboarding."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_git_prerequisite as git_prereq
from yoke_cli.config import project_git_macos_tools


def _which(*present: str):
    def _lookup(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    return _lookup


@pytest.mark.parametrize(
    ("platform_name", "binaries", "expected"),
    [
        ("darwin", ("brew",), "brew install git"),
        ("darwin", (), "xcode-select --install"),
        ("linux", ("dnf", "sudo"), "sudo dnf install -y git"),
        ("linux", ("yum", "sudo"), "sudo yum install -y git"),
        ("linux", ("apt-get", "sudo"),
         "sudo apt-get update && sudo apt-get install -y git"),
        ("linux", ("apk", "sudo"), "sudo apk add git"),
        ("linux", ("zypper", "sudo"), "sudo zypper install -y git"),
        ("linux", ("pacman", "sudo"), "sudo pacman -Sy --noconfirm git"),
        ("freebsd", ("sudo",), "sudo pkg install -y git"),
        ("openbsd", ("doas",), "doas pkg_add git"),
    ],
)
def test_install_advice_uses_host_package_manager(
    platform_name: str,
    binaries: tuple[str, ...],
    expected: str,
) -> None:
    advice = git_prereq.install_advice(
        platform_name=platform_name,
        which=_which(*binaries),
    )

    assert advice.command == expected


def test_linux_without_known_package_manager_uses_generic_guidance() -> None:
    advice = git_prereq.install_advice(platform_name="linux", which=_which())

    assert advice.command is None
    assert "package named git" in advice.note


def test_windows_guidance_names_unsupported_native_path() -> None:
    advice = git_prereq.install_advice(platform_name="win32", which=_which())

    assert advice.command is None
    assert "not supported" in advice.note
    assert "WSL" in advice.note


def test_require_git_available_raises_platform_specific_message() -> None:
    with pytest.raises(git_prereq.MissingGitError) as excinfo:
        git_prereq.require_git_available(
            platform_name="linux",
            which=_which("dnf", "sudo"),
        )

    message = str(excinfo.value)
    assert "git is required" in message
    assert "sudo dnf install -y git" in message


def test_install_advice_carries_structured_linux_install_steps() -> None:
    advice = git_prereq.install_advice(
        platform_name="linux",
        which=_which("dnf", "sudo"),
        is_root=lambda: False,
    )

    assert advice.command == "sudo dnf install -y git"
    assert advice.run_steps == (("sudo", "-n", "dnf", "install", "-y", "git"),)


def test_macos_command_line_tools_install_is_user_handoff() -> None:
    advice = git_prereq.install_advice(platform_name="darwin", which=_which())

    assert advice.command == "xcode-select --install"
    assert advice.run_steps == (("/usr/bin/xcode-select", "--install"),)
    assert advice.requires_user_completion is True
    assert git_prereq.install_action_label(advice) == "Install Apple Tools"


def test_macos_git_ready_does_not_probe_xcode_select(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    monkeypatch.setattr(project_git_macos_tools, "MAC_CLT_GIT", tmp_path / "git")
    monkeypatch.setattr(
        project_git_macos_tools,
        "MAC_DEVELOPER_DIR_LINK",
        tmp_path / "xcode_select_link",
    )

    def _runner(_args, **_kwargs):
        raise AssertionError("developer_git_ready must not invoke xcode-select")

    assert not project_git_macos_tools.developer_git_ready(
        runner=_runner,
        timeout=1,
    )


def test_macos_git_ready_accepts_developer_dir_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    developer_dir = tmp_path / "Xcode.app/Contents/Developer"
    git = developer_dir / "usr/bin/git"
    git.parent.mkdir(parents=True)
    git.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("DEVELOPER_DIR", str(developer_dir))
    monkeypatch.setattr(project_git_macos_tools, "MAC_CLT_GIT", tmp_path / "git")
    monkeypatch.setattr(
        project_git_macos_tools,
        "MAC_DEVELOPER_DIR_LINK",
        tmp_path / "xcode_select_link",
    )

    assert project_git_macos_tools.developer_git_ready(
        runner=lambda _args, **_kwargs: None,
        timeout=1,
    )


def test_macos_git_ready_accepts_selected_developer_dir_link(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    developer_dir = tmp_path / "Developer"
    git = developer_dir / "usr/bin/git"
    git.parent.mkdir(parents=True)
    git.write_text("#!/bin/sh\n", encoding="utf-8")
    link = tmp_path / "xcode_select_link"
    link.symlink_to(developer_dir)
    monkeypatch.setattr(project_git_macos_tools, "MAC_CLT_GIT", tmp_path / "git")
    monkeypatch.setattr(project_git_macos_tools, "MAC_DEVELOPER_DIR_LINK", link)

    assert project_git_macos_tools.developer_git_ready(
        runner=lambda _args, **_kwargs: None,
        timeout=1,
    )


def test_macos_label_parser_picks_latest_command_line_tools() -> None:
    output = """
    * Label: Command Line Tools for Xcode-15.9
        Title: Command Line Tools for Xcode, Version: 15.9
    * Label: Command Line Tools for Xcode-15.10
        Title: Command Line Tools for Xcode, Version: 15.10
    """

    assert (
        project_git_macos_tools.latest_command_line_tools_label(output)
        == "Command Line Tools for Xcode-15.10"
    )


def test_install_git_tries_macos_terminal_clt_before_handoff() -> None:
    state = {"installed": False, "calls": []}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/tmp/git" if state["installed"] else None
        if name == "sudo":
            return "/usr/bin/sudo"
        return None

    def _runner(args, **_kwargs):
        state["calls"].append(tuple(args))
        if args == ["/usr/sbin/softwareupdate", "-l"]:
            return subprocess.CompletedProcess(
                args,
                0,
                "* Label: Command Line Tools for Xcode-15.10\n",
                "",
            )
        if args[:3] == ["sudo", "-n", "/usr/sbin/softwareupdate"]:
            state["installed"] = True
        return subprocess.CompletedProcess(args, 0, "", "")

    def _probe_runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, "git version 2.0", "")

    advice = git_prereq.install_git(
        platform_name="darwin",
        which=_which,
        is_root=lambda: False,
        runner=_runner,
        probe_runner=_probe_runner,
    )

    assert advice.requires_user_completion is False
    assert state["calls"] == [
        ("/usr/sbin/softwareupdate", "-l"),
        (
            "sudo",
            "-n",
            "/usr/sbin/softwareupdate",
            "-i",
            "Command Line Tools for Xcode-15.10",
        ),
        (
            "sudo",
            "-n",
            "/usr/bin/xcode-select",
            "--switch",
            "/Library/Developer/CommandLineTools",
        ),
    ]


def test_install_git_falls_back_to_macos_gui_handoff_without_sudo() -> None:
    calls = []

    def _runner(args, **_kwargs):
        calls.append(tuple(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    advice = git_prereq.install_git(
        platform_name="darwin",
        which=_which(),
        is_root=lambda: False,
        runner=_runner,
    )

    assert advice.requires_user_completion is True
    assert calls == [("/usr/bin/xcode-select", "--install")]


def test_finalize_git_install_switches_to_macos_command_line_tools(
    monkeypatch,
) -> None:
    calls = []

    class _Root:
        def exists(self) -> bool:
            return True

        def __str__(self) -> str:
            return "/Library/Developer/CommandLineTools"

    monkeypatch.setattr(project_git_macos_tools, "MAC_CLT_ROOT", _Root())

    def _runner(args, **_kwargs):
        calls.append(tuple(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    git_prereq.finalize_git_install(
        platform_name="darwin",
        which=_which("sudo"),
        is_root=lambda: False,
        runner=_runner,
    )

    assert calls == [
        (
            "sudo",
            "-n",
            "/usr/bin/xcode-select",
            "--switch",
            "/Library/Developer/CommandLineTools",
        )
    ]


def test_install_advice_without_sudo_is_manual_only() -> None:
    advice = git_prereq.install_advice(
        platform_name="linux",
        which=_which("dnf"),
        is_root=lambda: False,
    )

    assert advice.command == "dnf install -y git"
    assert advice.run_steps == ()
    assert "root" in advice.note


def test_install_advice_as_root_uses_direct_package_manager() -> None:
    advice = git_prereq.install_advice(
        platform_name="linux",
        which=_which("dnf"),
        is_root=lambda: True,
    )

    assert advice.command == "dnf install -y git"
    assert advice.run_steps == (("dnf", "install", "-y", "git"),)


def test_git_available_requires_working_git_binary() -> None:
    def _runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 72, "", "developer tools missing")

    assert not git_prereq.git_available(
        platform_name="linux",
        which=_which("git"),
        runner=_runner,
    )


def test_install_git_runs_steps_then_verifies_git_available() -> None:
    state = {"installed": False, "calls": []}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git" if state["installed"] else None
        if name in {"dnf", "sudo"}:
            return f"/usr/bin/{name}"
        return None

    def _runner(args, **_kwargs):
        state["calls"].append(tuple(args))
        state["installed"] = True
        return subprocess.CompletedProcess(args, 0, "", "")

    def _probe_runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, "git version 2.0", "")

    git_prereq.install_git(
        platform_name="linux",
        which=_which,
        is_root=lambda: False,
        runner=_runner,
        probe_runner=_probe_runner,
    )

    assert state["calls"] == [("sudo", "-n", "dnf", "install", "-y", "git")]


def test_install_git_surfaces_command_failure() -> None:
    def _runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, "", "sudo: a password is required")

    with pytest.raises(git_prereq.GitInstallError) as excinfo:
        git_prereq.install_git(
            platform_name="linux",
            which=_which("dnf", "sudo"),
            is_root=lambda: False,
            runner=_runner,
        )

    assert "sudo -n dnf install -y git exited with 1" in str(excinfo.value)
    assert "password" in str(excinfo.value)
