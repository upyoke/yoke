"""Explicit mission provisioning restores a profile before daemon startup."""

import json

import pytest

from yoke_cli.commands import qa_browser_lifecycle as lifecycle
from yoke_cli.commands import qa_browser_profile_baseline as profiles
from yoke_harness import browser_client, browser_runtime_home


@pytest.fixture
def provisioning(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(browser_runtime_home, "ensure_materialized", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_ensure_node_toolchain", lambda **_: [])
    monkeypatch.setattr(
        lifecycle,
        "_browser_readiness",
        lambda *_, **__: {"daemon": {"status": "stopped"}},
    )
    monkeypatch.setattr(
        lifecycle, "_profile_dir_arg", lambda _: str(tmp_path / "profile")
    )
    monkeypatch.setattr(
        profiles,
        "restore_profile_baseline",
        lambda *args: events.append(("restore", args)) or {"restored": True},
    )
    monkeypatch.setattr(
        browser_client,
        "daemon_start",
        lambda **kw: events.append(("start", kw)) or {"status": "running"},
    )
    return events


def test_setup_restores_only_when_explicit_and_before_start(provisioning, capsys):
    assert (
        lifecycle.qa_browser_setup(
            [
                "--project",
                "yoke",
                "--profile-baseline",
                "/var/lib/goldens/profile",
                "--json",
            ]
        )
        == 0
    )
    assert [event[0] for event in provisioning] == ["restore", "start"]
    assert provisioning[0][1] == ("yoke", "/var/lib/goldens/profile")
    assert json.loads(capsys.readouterr().out)["profile_restore"]["restored"] is True


def test_default_setup_never_restores_profile(provisioning):
    assert lifecycle.qa_browser_setup(["--project", "yoke", "--json"]) == 0
    assert [event[0] for event in provisioning] == ["start"]


def test_dry_run_does_not_restore_or_start(provisioning):
    assert (
        lifecycle.qa_browser_setup(
            [
                "--dry-run",
                "--project",
                "yoke",
                "--profile-baseline",
                "/var/lib/goldens/profile",
                "--json",
            ]
        )
        == 0
    )
    assert provisioning == []


def test_restore_requires_project_and_does_not_start(provisioning):
    assert (
        lifecycle.qa_browser_setup(
            ["--profile-baseline", "/var/lib/goldens/profile", "--json"]
        )
        == 2
    )
    assert provisioning == []


def test_restore_refusal_prevents_daemon_start(provisioning, monkeypatch, capsys):
    def refuse(*_):
        raise RuntimeError("browser_profile_baseline_identity_mismatch")

    monkeypatch.setattr(profiles, "restore_profile_baseline", refuse)
    assert (
        lifecycle.qa_browser_setup(
            [
                "--project",
                "yoke",
                "--profile-baseline",
                "/var/lib/goldens/profile",
                "--json",
            ]
        )
        == 2
    )
    assert provisioning == []
    assert (
        json.loads(capsys.readouterr().out)["error"]
        == "browser_profile_baseline_identity_mismatch"
    )
