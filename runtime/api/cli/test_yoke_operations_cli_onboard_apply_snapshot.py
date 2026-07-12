"""Replay-safe onboarding apply snapshot coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_operations_cli_onboard_apply_report import _preview
from yoke_cli.config import onboard_apply_report
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
from yoke_cli.config.project_publish_support import PublishRequest


def test_apply_report_carries_replay_safe_input_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "fresh-checkout"
    publish = PublishRequest(
        owner="octo-org",
        name="widget",
        user_login="octocat",
        token="publish-secret",
        api_url="https://api.github.example",
        private=True,
    )
    clone = ClonePlan(
        outcome="make-it-mine",
        keep_upstream=True,
        publish=publish,
        fallback_token="clone-secret",
        fork_api_url="https://api.github.example",
    )

    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token": "yoke-secret",
            "token_source_kind": "argument",
            "machine_github_choice": "connect",
            "project_mode": "clone-remote",
            "project_remote_url": "https://github.com/octo/source.git",
            "project_checkout": str(checkout),
            "project_slug": "widget",
            "project_name": "Widget",
            "project_github_repo": "octo-org/widget",
            "project_default_branch": "main",
            "project_public_item_prefix": "WIDG",
            "project_github_adoption": GITHUB_ADOPTION_APP_BINDING,
            "project_clone": clone,
        },
    )

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    snapshot = payload["input_snapshot"]
    assert snapshot["env_name"] == "stage"
    assert snapshot["project"]["slug"] == "widget"
    assert snapshot["project"]["clone"]["outcome"] == "make-it-mine"
    assert snapshot["project"]["clone"]["publish"]["owner"] == "octo-org"
    assert snapshot["checkout_provenance"] == {
        "path": str(checkout),
        "project_mode": "clone-remote",
        "existed_before_apply": False,
        "created_by_run": True,
        "safe_to_preserve_for_new_target": True,
    }
    serialized = json.dumps(payload)
    assert "yoke-secret" not in serialized
    assert "machine-gh-secret" not in serialized
    assert "publish-secret" not in serialized
    assert "clone-secret" not in serialized


def test_local_checkout_snapshot_is_not_marked_as_run_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "existing"
    checkout.mkdir()
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "project_mode": "local-checkout",
            "project_checkout": str(checkout),
        },
    )

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    provenance = payload["input_snapshot"]["checkout_provenance"]
    assert provenance["existed_before_apply"] is True
    assert provenance["created_by_run"] is False
    assert provenance["safe_to_preserve_for_new_target"] is False
