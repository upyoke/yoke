"""Linux onboarding provisions the same runtime used at agent time."""

from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_apply_runtime
from yoke_harness import browser_setup
from yoke_harness import python_venv_dependencies


@pytest.fixture(autouse=True)
def stub_venv_setup(monkeypatch):
    monkeypatch.setattr(
        python_venv_dependencies, "ensure_venv_support", lambda **kw: None
    )


@pytest.mark.parametrize(
    "platform, expected", [("linux", 1), ("darwin", 0), ("win32", 0)]
)
def test_onboarding_sets_up_browser_on_linux(
    stub_onboard_browser_setup, monkeypatch, platform, expected
):
    calls = []
    report = {}
    monkeypatch.setattr(
        onboard_apply_runtime, "sys", SimpleNamespace(platform=platform, stderr=None)
    )
    monkeypatch.setattr(
        browser_setup, "ensure_browser_runtime", lambda **kwargs: calls.append(kwargs)
    )
    stub_onboard_browser_setup(None, report)
    assert len(calls) == expected
    assert ("browser_setup" in report) == bool(expected)


def test_onboarding_preserves_named_browser_setup_failure(
    stub_onboard_browser_setup, monkeypatch
):
    monkeypatch.setattr(
        onboard_apply_runtime, "sys", SimpleNamespace(platform="linux", stderr=None)
    )

    def refuse(**kwargs):
        raise RuntimeError(
            "browser_system_packages_unavailable: libX11.so.6; enable sudo"
        )

    monkeypatch.setattr(browser_setup, "ensure_browser_runtime", refuse)
    report = {}
    with pytest.raises(RuntimeError, match="browser_system_packages_unavailable"):
        stub_onboard_browser_setup(None, report)
    assert "browser_setup" not in report


def test_terminal_handoff_surrounds_browser_setup_and_resumes_on_failure():
    from contextlib import contextmanager
    from yoke_cli.config.onboard_apply_runtime import BROWSER_SETUP_ACTION
    from yoke_cli.config.onboard_browser_terminal import browser_terminal_progress

    events = []

    @contextmanager
    def suspend():
        events.append("suspended")
        try:
            yield
        finally:
            events.append("resumed")

    app = SimpleNamespace(suspend=suspend)
    browser_terminal_progress(app, "other-step", "running")
    assert events == []
    browser_terminal_progress(app, BROWSER_SETUP_ACTION, "running")
    assert events == ["suspended"]
    browser_terminal_progress(app, BROWSER_SETUP_ACTION, "failed")
    assert events == ["suspended", "resumed"]
    browser_terminal_progress(app, BROWSER_SETUP_ACTION, "done")
    assert events == ["suspended", "resumed"]


def test_venv_failure_stops_setup_before_browser_or_relay(
    stub_onboard_browser_setup, monkeypatch
):
    from yoke_cli.config import onboard_session_relay

    monkeypatch.setattr(
        onboard_apply_runtime, "sys", SimpleNamespace(platform="linux", stderr=None)
    )

    def refuse(**kwargs):
        raise RuntimeError(
            "python_venv_package_install_failed: python3.12-venv: apt lock held"
        )

    monkeypatch.setattr(python_venv_dependencies, "ensure_venv_support", refuse)
    monkeypatch.setattr(
        browser_setup, "ensure_browser_runtime", lambda **kw: pytest.fail("browser ran")
    )
    monkeypatch.setattr(
        onboard_session_relay, "apply", lambda *a, **kw: pytest.fail("relay ran")
    )
    monkeypatch.setattr(
        onboard_apply_runtime, "_setup_browser", stub_onboard_browser_setup
    )
    progress = []
    with pytest.raises(RuntimeError, match="python3.12-venv: apt lock held"):
        onboard_apply_runtime.apply(
            config_path=None,
            reuse={"temp_root": True, "cache_dir": True},
            harness_posture=False,
            progress=lambda *args: progress.append(args),
            report={},
            local_destination=False,
            environment="selected",
        )
    assert progress[-1][-1] == "failed"
