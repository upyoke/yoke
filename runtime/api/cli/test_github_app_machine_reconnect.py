from __future__ import annotations

import json
from pathlib import Path
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _api_opener,
    _device_opener,
    _explicit_profile,
)
from yoke_cli.config import github_machine


def test_reconnect_discovery_failure_preserves_cached_access_snapshot(
    tmp_path: Path, monkeypatch,
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
            **_explicit_profile(),
            device_opener=_device_opener(),
            api_opener=unavailable,
            browser_open=lambda url: True,
            sleep=lambda seconds: None,
            monotonic=lambda: 0,
        )

    stored = json.loads(config.read_text(encoding="utf-8"))["github"]
    assert stored["installations"] == original["installations"]
    assert stored["repositories"] == original["repositories"]
    assert stored == original
