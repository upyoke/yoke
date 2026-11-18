"""WSL hands URLs to Windows through wslview or PowerShell, recording failures."""

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import hosted_machine_browser as browser

URL = "http://localhost:8060/?token=a&other=b"
POSIX_FAKE = pytest.mark.posix_only(
    reason="fake powershell.exe is a #!/bin/sh script; the WSL opener runs only on Linux"
)


def _fake_powershell(bin_dir: Path, status: int) -> Path:
    """Write a powershell.exe that records its argv and URL environment."""
    script = bin_dir / "powershell.exe"
    script.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$0.argv"\n'
        'printf "%s\\n%s\\n" "$YOKE_OPEN_URL" "$WSLENV" > "$0.env"\n'
        f'[ {status} -eq 0 ] || echo "Start-Process refused" >&2\n'
        f"exit {status}\n"
    )
    script.chmod(0o755)
    return script


@pytest.fixture()
def wsl_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    # webbrowser's POSIX helpers would inherit the terminal; WSL never uses it.
    monkeypatch.setattr(
        browser.webbrowser, "open", lambda _: pytest.fail("webbrowser.open used")
    )
    return bin_dir


@POSIX_FAKE
def test_powershell_receives_the_url_only_through_the_environment(wsl_path):
    script = _fake_powershell(wsl_path, 0)
    result = browser.open_url(
        URL, platform="linux", environ={"WSL_DISTRO_NAME": "Ubuntu", "WSLENV": "A/p"}
    )
    assert result == browser.BrowserOpenResult(
        opened=True, method="powershell.exe", reason="wslview unavailable on PATH"
    )
    argv = Path(f"{script}.argv").read_text().splitlines()
    assert argv == [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Start-Process $env:YOKE_OPEN_URL",
    ]
    assert all(URL not in arg for arg in argv)
    assert Path(f"{script}.env").read_text().splitlines() == [URL, "A/p:YOKE_OPEN_URL"]


@POSIX_FAKE
def test_a_refused_start_process_is_recorded_as_not_opened(wsl_path):
    _fake_powershell(wsl_path, 1)
    result = browser.open_url(
        URL, platform="linux", environ={"WSL_DISTRO_NAME": "Ubuntu"}
    )
    assert not result.opened
    assert result.method is None
    assert result.reason == (
        "wslview unavailable on PATH; "
        "powershell.exe exited 1: Start-Process refused"
    )


def test_wslview_wins_before_powershell(wsl_path, monkeypatch):
    calls = []
    monkeypatch.setattr(browser.shutil, "which", lambda name: "/bin/" + name)

    def run(argv, **kwargs):
        calls.append((argv, kwargs.get("env")))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    result = browser.open_url(
        URL, platform="linux", environ={"WSL_DISTRO_NAME": "Ubuntu"}
    )
    assert result.opened and result.method == "wslview"
    assert calls == [(["/bin/wslview", URL], None)]


def test_wsl_missing_openers_report_recovery_evidence(wsl_path):
    result = browser.open_url(
        "https://example.invalid",
        platform="linux",
        environ={"WSL_INTEROP": "/run/interop"},
    )
    assert not result.opened
    assert "wslview unavailable" in result.reason
    assert "powershell.exe unavailable" in result.reason


def test_an_injected_opener_never_reaches_the_windows_browser(monkeypatch):
    monkeypatch.setattr(
        browser.shutil, "which", lambda name: pytest.fail(f"probed {name}")
    )
    result = browser.open_url(
        "https://example.invalid",
        platform="linux",
        environ={"WSL_DISTRO_NAME": "Ubuntu"},
        browser_open=lambda _: False,
    )
    assert result == browser.BrowserOpenResult(
        opened=False, reason="webbrowser.open returned False"
    )


def test_wsl_over_ssh_opens_nothing(wsl_path):
    script = _fake_powershell(wsl_path, 0)
    result = browser.open_url(
        URL,
        platform="linux",
        environ={"WSL_DISTRO_NAME": "Ubuntu", "SSH_CONNECTION": "10.0.0.2 1 10.0.0.1 22"},
    )
    assert result == browser.BrowserOpenResult(
        opened=False, reason="browser_display_unavailable"
    )
    assert not Path(f"{script}.argv").exists()
