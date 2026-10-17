"""Browser setup commands have bounded, named timeout failures."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import browser_setup


@pytest.mark.parametrize(
    ("command", "reason", "seconds"),
    [
        ("npm", "browser_npm_install_timeout", 180),
        ("node", "browser_chromium_probe_timeout", 40),
        ("npx", "browser_chromium_install_timeout", 300),
    ],
)
def test_browser_bootstrap_timeout_names_step_and_recovery(
    tmp_path, monkeypatch, command, reason, seconds
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("YOKE_BROWSER_AUTOINSTALL", "1")
    browser = tmp_path / "browser"
    browser.mkdir()
    if command != "npm":
        (browser / "node_modules/playwright").mkdir(parents=True)
    toolchain = SimpleNamespace(
        node="node", npm="npm", npx="npx", command_env=lambda: {}
    )

    def run(argv, **kwargs):
        assert kwargs["timeout"] > 0
        if argv[0] == command:
            assert kwargs["timeout"] == seconds
            raise subprocess.TimeoutExpired(argv, seconds)
        return subprocess.CompletedProcess(argv, 0, "missing", "")

    monkeypatch.setattr(browser_setup.terminal_detached_process, "run", run)
    with pytest.raises(RuntimeError, match=reason) as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert f"exceeded {seconds} seconds" in str(failure.value)
    assert "retry yoke qa browser setup" in str(failure.value)
