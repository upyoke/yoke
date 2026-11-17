"""Missing Git on a Windows client gets native installation guidance."""

import pytest

from yoke_cli.config import project_git_prerequisite

pytestmark = pytest.mark.windows


def test_windows_git_advice_keeps_setup_on_the_native_client():
    advice = project_git_prerequisite.install_advice(
        platform_name="win32", which=lambda _name: None,
    )

    assert advice.command is None  # Install outside setup, then retry.
    assert not advice.run_steps
    assert "winget install --id Git.Git -e" in advice.note
    assert "https://git-scm.com/download/win" in advice.note
    assert "new terminal" in advice.note
    assert "Try again" in advice.note
    assert "WSL" not in advice.note
    assert "not supported" not in advice.note
