"""Deferred editable install for "Develop Yoke itself".

The editable install repoints the tool venv `yoke` runs from, deleting the product
wheel the wizard process depends on — so it must run AFTER the UI closes. The in-UI
apply does source-link (via PYTHONPATH, needing no editable install) and records a
marker; the post-UI step runs the editable install and plain-prints the outcome.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.commands.adapters import onboard_project_args
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import dev_setup
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import yoke_dev_access


def _yoke_source_checkout(root: Path) -> Path:
    (root / "runtime" / "harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8",
    )
    return root


def test_pending_dev_install_marker_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    assert project_onboard_apply.pop_pending_dev_install(config) is None
    project_onboard_apply.record_pending_dev_install(tmp_path / "co", config)
    assert project_onboard_apply.pop_pending_dev_install(config) == str(tmp_path / "co")
    # Popped once — cleared, so the post-UI step never double-runs.
    assert project_onboard_apply.pop_pending_dev_install(config) is None


def test_source_dev_project_mode_needs_only_checkout() -> None:
    parsed = argparse.Namespace(
        project_mode=onboard_config.PROJECT_MODE_SOURCE_DEV_ADMIN,
        project_checkout="/src/yoke",
        project_slug=None,
        project_name=None,
        project_default_branch=None,
        project_public_item_prefix=None,
        project_remote_url=None,
        project_github_repo=None,
    )

    assert onboard_project_args.project_prompt_missing(parsed) is False


def test_source_dev_defaults_are_filled_for_noninteractive_adapter() -> None:
    defaults = onboard_adapter._source_dev_project_defaults(
        onboard_config.PROJECT_MODE_SOURCE_DEV_ADMIN
    )

    assert defaults == {
        "slug": yoke_dev_access.YOKE_PROJECT_SLUG,
        "name": yoke_dev_access.YOKE_PROJECT_NAME,
        "github_repo": yoke_dev_access.YOKE_GITHUB_REPO,
        "default_branch": yoke_dev_access.YOKE_DEFAULT_BRANCH,
        "public_item_prefix": yoke_dev_access.YOKE_PUBLIC_ITEM_PREFIX,
    }


def test_finish_pending_dev_install_uses_selected_stream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    root = _yoke_source_checkout(tmp_path / "yoke")
    project_onboard_apply.record_pending_dev_install(root, config)
    monkeypatch.setattr(
        dev_setup,
        "run_editable_install_step",
        lambda _root: {"ok": True},
    )
    stream = io.StringIO()

    onboard_adapter._finish_pending_dev_install(str(config), stream=stream)

    output = stream.getvalue()
    assert "Finalizing the Yoke dev install" in output
    assert str(root) in output
    assert project_onboard_apply.pop_pending_dev_install(config) is None


def test_source_link_subprocess_puts_checkout_on_pythonpath(
    tmp_path: Path, monkeypatch
) -> None:
    # Source-link resolves the checkout via PYTHONPATH, so it needs NO editable
    # install to be in place yet (that is deferred).
    root = _yoke_source_checkout(tmp_path / "yoke")
    captured: dict = {}

    class _Ok:
        returncode = 0
        stdout = '{"mode": "source-link", "warnings": []}'
        stderr = ""

    monkeypatch.setattr(
        dev_setup.subprocess, "run",
        lambda command, **kwargs: captured.update(env=kwargs.get("env")) or _Ok(),
    )
    dev_setup._run_source_link_subprocess(root)

    pythonpath = captured["env"]["PYTHONPATH"]
    assert str(root / "packages" / "yoke-core" / "src") in pythonpath
    assert str(root) in pythonpath  # top-level `runtime`


def test_run_editable_install_step_ok(tmp_path: Path, monkeypatch) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    monkeypatch.setattr(dev_setup, "_run_editable_install", lambda r: {"ran": True})
    assert dev_setup.run_editable_install_step(root) == {
        "ok": True, "editable_install": {"ran": True},
    }


def test_run_editable_install_step_captures_failure(
    tmp_path: Path, monkeypatch
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")

    def _boom(_root):
        raise dev_setup.DevSetupError("no uv")

    monkeypatch.setattr(dev_setup, "_run_editable_install", _boom)
    outcome = dev_setup.run_editable_install_step(root)
    assert outcome["ok"] is False
    assert "no uv" in outcome["error"]
