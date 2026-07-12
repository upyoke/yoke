"""Transactional replacement coverage for machine GitHub authorization."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _alternate_profile_opener,
    _api_opener,
    _device_opener,
    _explicit_profile,
)
from yoke_cli.config import github_machine, writer


def test_reconnect_config_failure_keeps_old_credential_and_cleans_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config, **_explicit_profile(),
        device_opener=_device_opener(), api_opener=_api_opener(installed=True),
        browser_open=lambda url: True, sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    original = json.loads(config.read_text(encoding="utf-8"))
    old_credential = Path(
        original["github"]["authorization"]["refresh_credential_ref"]
    )
    before = set(old_credential.parent.glob("github-app-user-*.json"))

    def fail_write(*args, **kwargs):
        raise writer.MachineConfigWriteError("simulated config write failure")

    monkeypatch.setattr(writer, "set_github", fail_write)
    with pytest.raises(
        github_machine.GitHubMachineError,
        match="simulated config write failure",
    ):
        github_machine.connect(
            config_path=config, **_explicit_profile(),
            device_opener=_device_opener(),
            api_opener=_api_opener(installed=True),
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert old_credential.is_file()
    assert json.loads(config.read_text(encoding="utf-8")) == original
    assert set(old_credential.parent.glob("github-app-user-*.json")) == before


def test_reconnect_keyboard_interrupt_keeps_old_config_and_cleans_new_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=True),
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    before = config.read_bytes()
    old_credential = Path(
        json.loads(before)["github"]["authorization"]["refresh_credential_ref"]
    )

    monkeypatch.setattr(
        writer,
        "set_github",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        github_machine.connect(
            config_path=config,
            **_explicit_profile(),
            device_opener=_device_opener(),
            api_opener=_api_opener(installed=True),
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert config.read_bytes() == before
    assert list(old_credential.parent.glob("github-app-user-*.json")) == [
        old_credential,
    ]


def test_reconnect_discovery_failure_preserves_last_known_good_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=True),
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    before = config.read_bytes()
    old_credential = Path(
        json.loads(before)["github"]["authorization"][
            "refresh_credential_ref"
        ]
    )

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="previous connection and credential were preserved",
    ):
        github_machine.connect(
            config_path=config,
            service_api_url="https://other.yoke.example",
            profile_opener=_alternate_profile_opener,
            replace_profile=True,
            device_opener=_device_opener(),
            api_opener=unavailable,
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    assert config.read_bytes() == before
    assert old_credential.is_file()
    assert list(old_credential.parent.glob("github-app-user-*.json")) == [
        old_credential
    ]


def test_explicit_reconnect_can_replace_a_different_verified_app_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=True),
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    original = json.loads(config.read_text(encoding="utf-8"))["github"]
    old_credential = Path(
        original["authorization"]["refresh_credential_ref"]
    )

    report = github_machine.connect(
        config_path=config,
        service_api_url="https://other.yoke.example",
        profile_opener=_alternate_profile_opener,
        replace_profile=True,
        device_opener=_device_opener(),
        api_opener=_api_opener(
            installed=True, app_id=456, app_slug="yoke-other",
        ),
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    stored = json.loads(config.read_text(encoding="utf-8"))["github"]
    new_credential = Path(
        stored["authorization"]["refresh_credential_ref"]
    )
    assert report["ready"] is True
    assert stored["app_slug"] == "yoke-other"
    assert stored["client_id"] == "Iv1.other"
    assert new_credential.is_file()
    assert new_credential != old_credential
    assert not old_credential.exists()


def test_passive_connect_rejects_profile_change_before_device_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=True),
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    before = config.read_bytes()
    device_calls: list[str] = []

    def unexpected_device(request, timeout):
        device_calls.append(request.full_url)
        raise AssertionError("device authorization must not start")

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="explicit reconnect action",
    ):
        github_machine.connect(
            config_path=config,
            service_api_url="https://other.yoke.example",
            profile_opener=_alternate_profile_opener,
            device_opener=unexpected_device,
        )

    assert device_calls == []
    assert config.read_bytes() == before
