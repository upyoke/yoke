from __future__ import annotations

import json
from pathlib import Path
import urllib.error

from runtime.api.cli.test_github_app_machine_connection import (
    _api_opener,
    _device_opener,
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
        client_id="Iv1.local",
        app_slug="yoke-local",
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

    report = github_machine.connect(
        config_path=config,
        client_id="Iv1.local",
        app_slug="yoke-local",
        device_opener=_device_opener(),
        api_opener=unavailable,
        browser_open=lambda url: True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    stored = json.loads(config.read_text(encoding="utf-8"))["github"]
    assert stored["installations"] == original["installations"]
    assert stored["repositories"] == original["repositories"]
    assert report["access"]["repos"] == ["octo-org/app"]
    assert report["access"]["snapshot_source"] == "cached"
    assert report["access"]["repo_listing_ok"] is False
    assert report["ok"] is False
    assert report["ready"] is False
