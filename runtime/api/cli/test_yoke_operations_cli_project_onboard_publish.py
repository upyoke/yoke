"""Publish routing through create_project / onboard_existing.

The GitHub create + git push is mocked at the ``create_and_publish`` seam and
the dispatcher / installer / machine-config writes are stubbed, so these assert
the routing only: publish runs for create-new and local-checkout, is auto-
skipped when an unrelated remote already exists, retries when the selected repo
is already origin, and the created repo's full_name lands on the API payload.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import project_onboard
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import project_onboard_progress
from yoke_cli.config.project_publish_support import PublishRequest


@pytest.fixture
def _stub_backend(monkeypatch):
    """Stub dispatch + install + machine register so only routing is exercised."""
    dispatched: list[tuple[str, dict]] = []

    def _fake_dispatch(function_id, payload, config_path):
        dispatched.append((function_id, dict(payload)))
        if function_id == "projects.get":
            raise project_onboard.ProjectDispatchError(
                function_id, "not_found", "missing"
            )
        return {"project": {"id": 42, "slug": payload.get("slug"),
                            "github_repo": payload.get("github_repo")}}

    monkeypatch.setattr(project_onboard, "dispatch", _fake_dispatch)
    monkeypatch.setattr(
        project_onboard_apply.install_runner, "install",
        lambda *a, **k: {"installed": True},
    )
    monkeypatch.setattr(
        project_onboard_apply.machine_writer, "register_project",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(project_onboard_apply, "ensure_git_available", lambda: None)
    # The report/handoff assembly is out of scope here — the routing tests key
    # off the dispatched payload and the create_and_publish seam, not the
    # report shape. Stub it to a trivial dict so the install/handoff plumbing
    # does not need a fully-shaped install result.
    monkeypatch.setattr(
        project_onboard_apply, "applied_report",
        lambda *a, **k: {"applied": True},
    )
    return dispatched


def _publish() -> PublishRequest:
    return PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token="ghs_x",
    )


def _base_kwargs(checkout: Path) -> dict:
    return {
        "checkout": str(checkout),
        "slug": "widget",
        "name": "Widget",
        "org": None,
        "github_repo": None,
        "default_branch": "main",
        "public_item_prefix": "WIDG",
        "github_adoption_choice": "backlog-only",
        "config_path": None,
        "apply": True,
    }


def test_create_project_publishes_and_records_repo(tmp_path, monkeypatch, _stub_backend):
    calls: list = []
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda root, publish, **k: calls.append((root, publish))
        or {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: True,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: True)

    project_onboard.create_project(publish=_publish(), **_base_kwargs(tmp_path / "new"))

    assert len(calls) == 1
    created = next(p for fn, p in _stub_backend if fn == "projects.create")
    assert created["github_repo"] == "octocat/widget"


def test_fresh_create_refreshes_app_access_before_binding(
    tmp_path, monkeypatch, _stub_backend,
) -> None:
    events: list[str] = []
    github_config = {
        "api_url": "https://api.github.com",
        "repositories": [],
    }

    def _create(*_args, **_kwargs):
        events.append("publish")
        return {"full_name": "octocat/widget", "private": True}

    def _status(**_kwargs):
        events.append("refresh")
        github_config["repositories"] = [{
            "full_name": "octocat/widget",
            "repository_id": 88,
            "installation_id": 7,
        }]
        return {"ok": True}

    def _binding_dispatch(function_id, payload, _config_path, **_kwargs):
        if function_id == "projects.github_binding.bind":
            events.append("bind")
            assert payload["repository_id"] == 88
            assert payload["installation_id"] == 7
            return {
                "binding": {"status": "active"},
                "permission_status": {"ok": True},
            }
        assert function_id == "projects.update"
        events.append("sync-policy")
        assert payload["github_sync_mode"] == "enabled"
        return {"project": payload}

    monkeypatch.setattr(project_onboard, "create_and_publish", _create)
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda *_args: True,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda *_args: True)
    monkeypatch.setattr(project_onboard_progress.github_machine, "status", _status)
    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: github_config,
    )
    monkeypatch.setattr(
        project_onboard_progress.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        lambda **_kwargs: nullcontext(SimpleNamespace(
            token=SimpleNamespace(access_token="ghu_short_lived"),
            api_url="https://api.github.com",
        )),
    )
    monkeypatch.setattr(project_onboard_progress, "dispatch", _binding_dispatch)
    kwargs = _base_kwargs(tmp_path / "new")
    kwargs.update({
        "github_repo": "octocat/widget",
        "github_adoption_choice": "app-binding",
    })

    project_onboard.create_project(publish=_publish(), **kwargs)

    assert events == ["publish", "refresh", "bind", "sync-policy"]


def test_create_project_no_publish_does_not_create_repo(tmp_path, monkeypatch, _stub_backend):
    called = {"n": 0}
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: True,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: True)

    project_onboard.create_project(publish=None, **_base_kwargs(tmp_path / "new"))

    assert called["n"] == 0


def test_create_project_auto_skips_publish_when_remote_exists(
    tmp_path, monkeypatch, _stub_backend,
):
    called = {"n": 0}
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: False,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: False)

    project_onboard.create_project(publish=_publish(), **_base_kwargs(tmp_path / "new"))

    assert called["n"] == 0


def test_create_project_retries_publish_when_origin_matches(
    tmp_path, monkeypatch, _stub_backend,
):
    calls: list = []
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda root, publish, **k: calls.append((root, publish))
        or {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: True,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: False)

    project_onboard.create_project(publish=_publish(), **_base_kwargs(tmp_path / "new"))

    assert len(calls) == 1
    created = next(p for fn, p in _stub_backend if fn == "projects.create")
    assert created["github_repo"] == "octocat/widget"


def test_onboard_existing_publishes_for_plain_folder(tmp_path, monkeypatch, _stub_backend):
    folder = tmp_path / "code"
    folder.mkdir()
    calls: list = []
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda root, publish, **k: calls.append((root, publish))
        or {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: True,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: True)

    project_onboard.onboard_existing(publish=_publish(), **_base_kwargs(folder))

    assert len(calls) == 1
    created = next(p for fn, p in _stub_backend if fn == "projects.create")
    assert created["github_repo"] == "octocat/widget"


def test_onboard_existing_auto_skips_when_remote_exists(
    tmp_path, monkeypatch, _stub_backend,
):
    folder = tmp_path / "code"
    folder.mkdir()
    called = {"n": 0}
    monkeypatch.setattr(
        project_onboard, "create_and_publish",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    monkeypatch.setattr(
        project_onboard, "publish_checkout_needed", lambda root, publish: False,
    )
    monkeypatch.setattr(project_onboard, "init_repo_if_needed", lambda r, b: False)

    project_onboard.onboard_existing(publish=_publish(), **_base_kwargs(folder))

    assert called["n"] == 0
