"""Registered ``project.git.bootstrap``: local init, nested refuse, remotes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_cli.commands.adapters import project_git_bootstrap as adapter
from yoke_cli.config import project_git_bootstrap as boot
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_publish_request import PublishRequest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import function_authz_scope
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import _register_project_git_bootstrap
from yoke_core.domain.handlers import project_git_bootstrap as handler
from yoke_core.domain import yoke_function_registry


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _init_repo(root: Path, branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--initial-branch", branch)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")


def _publish() -> PublishRequest:
    return PublishRequest(
        owner="octocat", name="widget", user_login="octocat",
        token="ghs_x", private=True,
    )


def test_plain_folder_inits_gitignore_and_commit(tmp_path: Path) -> None:
    checkout = tmp_path / "app"
    result = boot.bootstrap_checkout(
        checkout, apply=True, create_remote=False,
    )
    assert result.initialized is True
    assert result.gitignore_written is True
    assert result.committed is True
    assert (checkout / ".git").is_dir()
    ignore = (checkout / ".gitignore").read_text(encoding="utf-8")
    assert ".worktrees/" in ignore
    assert "*.iso" in ignore
    assert "*.mp4" in ignore
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=checkout,
        stdout=subprocess.PIPE, check=True,
    )
    assert head.returncode == 0


def test_existing_repo_is_noop_and_does_not_overwrite_gitignore(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "app"
    _init_repo(checkout)
    (checkout / ".gitignore").write_text("# keep\n", encoding="utf-8")
    result = boot.bootstrap_checkout(
        checkout, apply=True, create_remote=False,
    )
    assert result.initialized is False
    assert "init" in result.skipped
    assert (checkout / ".gitignore").read_text(encoding="utf-8") == "# keep\n"


def test_nested_folder_inside_another_repo_refuses(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    _init_repo(outer)
    inner = outer / "inner"
    inner.mkdir()
    with pytest.raises(ProjectOnboardError, match="inside git worktree"):
        boot.bootstrap_checkout(inner, apply=True, create_remote=False)
    with pytest.raises(ProjectOnboardError, match="inside git worktree"):
        boot.bootstrap_checkout(inner, apply=False, create_remote=False)


def test_no_init_on_plain_folder_fails_loudly(tmp_path: Path) -> None:
    checkout = tmp_path / "plain"
    checkout.mkdir()
    with pytest.raises(ProjectOnboardError, match="not a git repository"):
        boot.bootstrap_checkout(
            checkout, apply=True, init_repo=False, create_remote=False,
        )


def test_no_create_remote_skips_publish(tmp_path: Path) -> None:
    called = {"n": 0}

    def _publish_fn(*_a, **_k):
        called["n"] += 1
        raise AssertionError("create_and_publish must not run")

    result = boot.bootstrap_checkout(
        tmp_path / "app",
        apply=True,
        create_remote=False,
        create_and_publish=_publish_fn,
    )
    assert "create-remote" in result.skipped
    assert called["n"] == 0
    assert result.remote_created is False


def test_existing_origin_is_never_replaced(tmp_path: Path) -> None:
    checkout = tmp_path / "app"
    _init_repo(checkout)
    _git(checkout, "remote", "add", "origin", "https://github.com/octocat/kept.git")
    called = {"n": 0}
    result = boot.bootstrap_checkout(
        checkout,
        apply=True,
        create_and_publish=lambda *a, **k: called.__setitem__("n", 1),
        publish_needed=lambda *a: True,
    )
    assert called["n"] == 0
    assert result.remote_created is False
    assert "create-remote" in result.skipped
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=checkout,
        stdout=subprocess.PIPE, text=True, check=True,
    )
    assert "octocat/kept" in url.stdout


def test_mocked_remote_create_is_private_and_can_bind(tmp_path: Path, monkeypatch) -> None:
    checkout = tmp_path / "widget"
    seen: list[PublishRequest] = []

    def _create(root, request, default_branch="main"):
        seen.append(request)
        return {"full_name": request.full_name, "private": request.private}

    monkeypatch.setattr(
        boot.remote, "bind_project",
        lambda slug, repo, _cfg: slug == "widget" and repo == "octocat/widget",
    )
    result = boot.bootstrap_checkout(
        checkout,
        apply=True,
        project_slug="widget",
        publish=_publish(),
        create_and_publish=_create,
        publish_needed=lambda *a: True,
    )
    assert result.remote_created is True
    assert result.github_repo == "octocat/widget"
    assert result.bound is True
    assert seen[0].private is True


def test_dry_run_plans_without_writing(tmp_path: Path) -> None:
    checkout = tmp_path / "app"
    result = boot.bootstrap_checkout(checkout, apply=False)
    assert result.dry_run is True
    assert any("git init" in step for step in result.planned)
    assert not checkout.exists()


def test_adapter_dispatch_is_local_only() -> None:
    with mock.patch.object(
        adapter, "dispatch_and_emit", return_value=0,
    ) as dispatched:
        adapter.project_git_bootstrap(["/tmp/app", "--yes"])
    kwargs = dispatched.call_args.kwargs
    assert kwargs.get("local_only") is True
    assert kwargs["payload"]["apply"] is True
    assert kwargs["function_id"] == "project.git.bootstrap"


def test_function_is_classified_client_local() -> None:
    assert function_authz_scope.is_explicit_client_local("project.git.bootstrap")


def test_handler_requires_global_target_and_checkout() -> None:
    bad_kind = FunctionCallRequest(
        function="project.git.bootstrap",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item"),
        payload={"checkout": "/tmp/app"},
    )
    outcome = handler.handle_project_git_bootstrap(bad_kind)
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"

    empty = FunctionCallRequest(
        function="project.git.bootstrap",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"checkout": "  "},
    )
    outcome = handler.handle_project_git_bootstrap(empty)
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_registrar_is_listed_and_live() -> None:
    yoke_function_registry.reset_registry_for_tests()
    try:
        init_register.register_all_handlers()
        entry = yoke_function_registry.lookup("project.git.bootstrap")
        assert entry is not None
        assert entry.target_kinds == ("global",)
        assert entry.adapter_status == "live"
        assert "project_repo_file_write" in entry.side_effects
        assert _register_project_git_bootstrap in init_register._DOMAIN_REGISTRARS
    finally:
        yoke_function_registry.reset_registry_for_tests()
