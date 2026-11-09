"""New-project publication attaches origin before onboarding installs."""

from types import SimpleNamespace

from yoke_cli.config import project_onboard_create as create
from yoke_cli.config import project_publish_support as publish_support
from yoke_cli.config import project_onboard_apply as apply
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_cli.project_repository_identity import assert_project_repository
from yoke_cli import project_repository_identity as identity


def test_create_and_publish_attaches_matching_origin_before_install(tmp_path, monkeypatch):
    import subprocess

    root = tmp_path / "new"
    events = []
    publish = PublishRequest(owner="example", name="widget", user_login="example", token="test")
    monkeypatch.setattr(publish_support, "ensure_initial_commit", lambda *a: None)
    monkeypatch.setattr(publish_support, "local_head_sha", lambda *a: "a" * 40)
    monkeypatch.setattr(publish_support.github_publish, "create_repo", lambda *a, **k: {
        "full_name": "example/widget", "private": True,
    })
    original_git = publish_support.run_git

    def git(root, *args, **kwargs):
        if args and args[0] == "push":
            events.append("publish")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return original_git(root, *args, **kwargs)

    monkeypatch.setattr(publish_support, "run_git", git)
    monkeypatch.setattr(identity, "_binding_status", lambda *a, **k: {
        "github_repo": "example/widget", "api_url": "https://api.github.com",
    })

    def finish(**kwargs):
        events.append("install")
        remote = subprocess.check_output(["git", "-C", str(root), "remote", "get-url", "origin"], text=True)
        assert remote.strip() == "https://github.com/example/widget.git"
        assert_project_repository(root, "widget")
        return {"installed": True}

    monkeypatch.setattr(apply, "finish_after_dispatch", finish)
    monkeypatch.setattr(create.progress_steps, "record_mutated_repository", lambda *a, **k: None)
    operations = create.CreateProjectOperations(
        create_and_publish=publish_support.create_and_publish,
        dispatch=lambda *a: {"project": {"id": 42}},
        finish_github_binding=lambda *a: None,
        init_repo_if_needed=publish_support.init_repo_if_needed,
        publish_checkout_needed=lambda *a: True,
        record_selected_repository_identity=lambda *a, **k: None,
    )
    result = create.create_project(
        operations=operations, checkout=root, slug="widget", name="Widget", org=None,
        github_repo=None, default_branch="main", public_item_prefix="WIDG",
        github_adoption_choice="disabled", config_path=None, apply=True, publish=publish,
    )
    assert result["installed"]
    assert events == ["publish", "install"]
