from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_local_checkout_identity
from yoke_cli.config import onboard_wizard_flow
from yoke_cli.config import onboard_wizard_flow_publish
from yoke_cli.config import onboard_project
from yoke_cli.config import project_clone_resume
from yoke_cli.config.onboard_wizard import WizardResult


class _LocalCheckoutShell(onboard_wizard_flow.WizardFlow):
    def __init__(self, checkout: Path) -> None:
        self.result = SimpleNamespace(
            config_path=str(checkout.parent / "config.json"),
            api_url="https://yoke.example",
            destination="hosted",
            project_github_repo=None,
            project_source_default_branch=None,
            token=None,
            token_file=None,
            token_source_kind="prompt",
        )
        self.slug_visits = 0
        self.error: BaseException | None = None

    def _goto_slug(self) -> None:
        self.slug_visits += 1

    def _goto_existing_project_lookup_error(self, exc, **_kwargs) -> None:
        self.error = exc

    def _yoke_token_for_project_lookup(self) -> None:
        return None


def _local_checkout_seams(monkeypatch, *, branch: str, remote: str | None) -> None:
    monkeypatch.setattr(
        existing_project_lookup,
        "find_local_project_reference",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        onboard_local_checkout_identity,
        "is_git_repo",
        lambda _path: True,
    )
    monkeypatch.setattr(
        project_clone_resume,
        "is_exact_worktree_root",
        lambda _path: True,
    )
    monkeypatch.setattr(
        onboard_local_checkout_identity.project_git_transport,
        "git_current_branch",
        lambda _path: branch,
    )
    monkeypatch.setattr(
        project_clone_resume,
        "remote_url",
        lambda *_args: remote,
    )


def test_local_checkout_records_current_branch_before_publish(
    tmp_path, monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _local_checkout_seams(
        monkeypatch,
        branch="trunk",
        remote="https://github.com/example/project.git",
    )
    shell = _LocalCheckoutShell(checkout)

    shell._after_local_checkout_source(str(checkout))

    assert shell.error is None
    assert shell.slug_visits == 1
    assert shell.result.project_source_default_branch == "trunk"
    assert shell.result.project_github_repo == "example/project"


def test_local_checkout_rejects_detached_head_before_publish(
    tmp_path, monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _local_checkout_seams(monkeypatch, branch="main", remote=None)
    monkeypatch.setattr(
        onboard_local_checkout_identity.project_git_transport,
        "git_current_branch",
        lambda _path: (_ for _ in ()).throw(RuntimeError("detached HEAD")),
    )
    shell = _LocalCheckoutShell(checkout)

    shell._after_local_checkout_source(str(checkout))

    assert shell.slug_visits == 0
    assert str(shell.error) == "detached HEAD"


def test_local_checkout_does_not_bind_foreign_remote(
    tmp_path, monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _local_checkout_seams(
        monkeypatch,
        branch="main",
        remote="https://gitlab.com/example/project.git",
    )
    shell = _LocalCheckoutShell(checkout)

    shell._after_local_checkout_source(str(checkout))

    assert shell.error is None
    assert shell.slug_visits == 1
    assert shell.result.project_github_repo is None


def test_origin_mismatch_never_echoes_embedded_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    secret = "ghp_origin_secret"
    monkeypatch.setattr(
        project_clone_resume,
        "is_exact_worktree_root",
        lambda _path: True,
    )
    monkeypatch.setattr(
        project_clone_resume,
        "remote_url",
        lambda *_args: (
            f"https://octocat:{secret}@github.com/foreign/repository.git"
        ),
    )

    with pytest.raises(RuntimeError) as caught:
        onboard_local_checkout_identity.require_matching_origin(
            checkout,
            github_repo="owner/demo",
            web_url="https://github.com",
        )

    assert secret not in str(caught.value)
    assert "unrecognized origin" in str(caught.value)


def test_linked_worktree_root_is_exact_but_nested_folder_is_not(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=source,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=source,
        check=True,
    )
    (source / "README.md").write_text("# source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=source,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "linked", str(linked)],
        cwd=source,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    nested = linked / "nested"
    nested.mkdir()

    assert project_clone_resume.is_exact_worktree_root(linked) is True
    assert project_clone_resume.is_exact_worktree_root(nested) is False


def test_local_checkout_publish_uses_detected_source_branch() -> None:
    class PublishShell(onboard_wizard_flow_publish.PublishFlow):
        result = SimpleNamespace(
            project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
            project_source_default_branch="release",
            project_github_repo=None,
            project_github_adoption=None,
        )
        branch: str | None = None

        def _after_branch(self, value: str) -> None:
            self.branch = value

        def _goto_input(self, *_args, **_kwargs) -> None:
            raise AssertionError("detected branch must not be prompted again")

    shell = PublishShell()
    shell._after_repo("example/project")

    assert shell.branch == "release"


def test_existing_remote_publish_skip_preserves_detected_repository(
    tmp_path, monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    class PublishShell(onboard_wizard_flow_publish.PublishFlow):
        result = SimpleNamespace(
            project_checkout=str(checkout),
            project_github_repo="example/project",
            project_keep_existing_remote=False,
        )
        forwarded_repo: str | None = None

        def _after_repo(self, value: str) -> None:
            self.forwarded_repo = value

    monkeypatch.setattr(
        onboard_wizard_flow_publish, "has_remote", lambda _path: True,
    )
    monkeypatch.setattr(
        onboard_wizard_flow_publish.onboard_local_checkout_identity,
        "require_matching_origin",
        lambda *_args, **_kwargs: None,
    )
    shell = PublishShell()

    shell._goto_publish_prompt()

    assert shell.result.project_keep_existing_remote is True
    assert shell.forwarded_repo == "example/project"


class _ModeShell(onboard_wizard_flow.WizardFlow):
    def __init__(self) -> None:
        self.result = WizardResult(
            config_path="/tmp/config.json",
            env_name="prod",
            api_url="https://api.example",
        )
        self.checked_mode: str | None = None
        self._preserve_project_fields_once = False

    def _check_project_git(self, mode: str) -> None:
        self.checked_mode = mode


def test_new_project_mode_traversal_clears_stale_flow_state() -> None:
    shell = _ModeShell()
    shell.result.project_publish_private = False
    shell.result.project_clone_outcome = "fork"
    shell.result.project_source_default_branch = "trunk"
    shell.result.existing_project_id = 42
    shell.result.project_github_adoption_preserve = True
    shell.result.project_keep_existing_remote = True

    shell._on_project_mode(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)

    assert shell.checked_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    assert shell.result.project_publish_private is True
    assert shell.result.project_clone_outcome is None
    assert shell.result.project_source_default_branch is None
    assert shell.result.existing_project_id is None
    assert shell.result.project_github_adoption_preserve is False
    assert shell.result.project_keep_existing_remote is False


def test_explicit_project_preset_is_preserved_once() -> None:
    shell = _ModeShell()
    shell.result.project_checkout = "/tmp/preset"
    shell.result.project_slug = "preset"
    shell._preserve_project_fields_once = True

    shell._on_project_mode(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)

    assert shell.result.project_checkout == "/tmp/preset"
    assert shell.result.project_slug == "preset"
    assert shell._preserve_project_fields_once is False
