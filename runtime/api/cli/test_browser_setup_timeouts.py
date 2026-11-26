"""Browser setup commands have bounded, named timeout failures."""

from yoke_contracts.testing.real_home_isolation import set_home

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import browser_setup


@pytest.mark.parametrize(
    ("command", "script", "reason", "seconds"),
    [
        ("npm", None, "browser_npm_install_timeout", 180),
        (
            "node",
            browser_setup.browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS,
            "browser_chromium_probe_timeout",
            40,
        ),
        ("npx", None, "browser_chromium_install_timeout", 300),
    ],
)
def test_browser_bootstrap_timeout_names_step_and_recovery(
    tmp_path, monkeypatch, command, script, reason, seconds
):
    set_home(monkeypatch, str(tmp_path))
    monkeypatch.setenv("YOKE_BROWSER_AUTOINSTALL", "1")
    browser = tmp_path / "browser"
    browser.mkdir()
    if command != "npm":
        (browser / "node_modules/playwright").mkdir(parents=True)
    toolchain = SimpleNamespace(
        node="node",
        npm="npm",
        npx="npx",
        package_command=lambda name, *args: [name, *args],
        command_env=lambda: {},
    )

    def run(argv, **kwargs):
        assert kwargs["timeout"] > 0
        if argv[0] == command and (script is None or argv[2] == script):
            assert kwargs["timeout"] == seconds
            raise subprocess.TimeoutExpired(argv, seconds)
        module_load = argv[-1] == browser_setup.PLAYWRIGHT_LOAD_PROBE_JS
        return subprocess.CompletedProcess(
            argv, 0, "ok" if module_load and command != "npm" else "missing", ""
        )

    monkeypatch.setattr(browser_setup.terminal_detached_process, "run", run)
    with pytest.raises(RuntimeError, match=reason) as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert f"exceeded {seconds} seconds" in str(failure.value)
    assert "retry yoke qa browser setup" in str(failure.value)
