"""Desktop config resolution follows the host's platform and XDG directory."""

from pathlib import Path

import pytest

from yoke_contracts import harness_unattended_posture as posture


@pytest.mark.parametrize("xdg", [None, "", "custom-config"])
@pytest.mark.parametrize("wsl", [False, True])
def test_linux_claude_config_and_review_name_the_same_path(
    monkeypatch, tmp_path: Path, xdg, wsl
):
    monkeypatch.setattr(posture.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    if wsl:
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    if xdg is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / xdg) if xdg else "")
    root = tmp_path / (xdg or ".config")
    expected = root / "Claude" / "claude_desktop_config.json"
    assert posture.claude_config_path() == expected
    assert posture.managed_config_paths()[posture.CLAUDE_FAMILY] == expected
    assert str(expected) in posture.posture_plan_summary()


def test_macos_claude_config_uses_application_support(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(posture.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ignored"))
    assert posture.claude_config_path() == (
        tmp_path / "Library/Application Support/Claude/claude_desktop_config.json"
    )
