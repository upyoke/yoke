"""Mapped dirty reads work without any claimed Yoke source checkout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from yoke_cli.main import main
from yoke_contracts.control_plane_locality import remote_control_plane
from yoke_core.domain import project_checkout_locations
from yoke_core.domain.handlers import worktree_dirty
from yoke_core.domain.yoke_function_dispatch import dispatch_local
from yoke_core.domain.yoke_function_registry import lookup


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def platform_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    checkout.mkdir()
    _git(checkout, "init")
    _git(
        checkout,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "Initial checkout",
    )
    monkeypatch.setattr(
        project_checkout_locations,
        "project_id_for_slug",
        lambda project: 23 if project == "platform" else None,
    )
    monkeypatch.setattr(
        project_checkout_locations.machine_config,
        "load_config",
        lambda *args: {
            "projects": [
                {
                    "project_id": 23,
                    "checkout": str(checkout),
                }
            ]
        },
    )
    # A Platform-only session has no source-dev execution authority. The read
    # must not try source-dev lane selection or any work-claim resolution.
    from yoke_core.tools import source_dev_run

    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        Mock(side_effect=AssertionError("no Yoke source lane")),
    )
    monkeypatch.setenv("YOKE_PROJECT", "platform")
    return checkout


def _run(monkeypatch, capsys, *args):
    from yoke_cli.commands import _helpers
    from yoke_cli.transport import https

    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        https,
        "resolve_https_connection",
        Mock(side_effect=AssertionError("must dispatch locally")),
    )
    with remote_control_plane():
        rc = main(
            ["worktree", "classify-dirty", "--project", "platform", "--json", *args]
        )
    captured = capsys.readouterr()
    return rc, json.loads(captured.out)


def test_platform_only_session_classifies_real_checkout(
    platform_checkout,
    monkeypatch,
    capsys,
):
    checkout = platform_checkout
    (checkout / "source.txt").write_text("original")
    _git(checkout, "add", "source.txt")
    _git(
        checkout,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "Tracked source",
    )
    (checkout / "source.txt").write_text("dirty")
    (checkout / "staged.txt").write_text("staged")
    _git(checkout, "add", "staged.txt")
    (checkout / "untracked.txt").write_text("untracked")
    (checkout / ".yoke/strategy").mkdir(parents=True)
    (checkout / ".yoke/strategy/PAD.md").write_text("bookkeeping")
    (checkout / ".worktrees/lane").mkdir(parents=True)
    (checkout / ".worktrees/lane/change.txt").write_text("lane")

    rc, response = _run(monkeypatch, capsys, "--exclude-worktrees")

    assert rc == 0
    assert response["success"] is True
    assert response["result"] == {
        "project": "platform",
        "checkout": str(checkout),
        "yoke_managed": [".yoke/strategy/PAD.md"],
        "user_authored": ["source.txt", "staged.txt", "untracked.txt"],
    }
    assert lookup("worktree.classify_dirty").side_effects == ()
    assert lookup("worktree.classify_dirty").minimum_serving_version == "next-release"


def test_clean_checkout_has_two_empty_lists(platform_checkout, monkeypatch, capsys):
    rc, response = _run(monkeypatch, capsys)
    assert rc == 0
    assert response["result"]["yoke_managed"] == []
    assert response["result"]["user_authored"] == []


def test_missing_mapping_refuses(monkeypatch, capsys):
    monkeypatch.setattr(worktree_dirty, "checkout_for_project_slug", lambda _: None)
    rc, response = _run(monkeypatch, capsys)
    assert rc != 0
    assert response["error"]["code"] == "project_checkout_unavailable"
    assert "yoke project register" in response["error"]["recovery_hint"]
    assert not response.get("result")


def test_invalid_checkout_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worktree_dirty, "checkout_for_project_slug", lambda _: tmp_path)
    rc, response = _run(monkeypatch, capsys)
    assert rc != 0
    assert response["error"]["code"] == "dirty_classification_failed"
    assert "Restore Git access" in response["error"]["recovery_hint"]


def test_timeout_refuses(platform_checkout, monkeypatch, capsys):
    monkeypatch.setattr(
        worktree_dirty.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("git", 10)),
    )
    rc, response = _run(monkeypatch, capsys)
    assert rc != 0
    assert response["error"]["code"] == "dirty_classification_failed"


def test_invalid_payload_is_named():
    response = dispatch_local(
        {
            "function": "worktree.classify_dirty",
            "target": {"kind": "global"},
            "actor": {"session_id": "client-local-test-session"},
            "payload": {},
        }
    )
    assert not response.success
    assert response.error.code == "payload_invalid"


def test_help_teaches_registered_read(capsys):
    assert main(["worktree", "classify-dirty", "--help"]) == 0
    assert "mapped checkout" in capsys.readouterr().out
