"""Review explains setup publication without changing Apply's transport."""

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import onboard_plan_labels, onboard_publication, onboard_report
from yoke_cli.config import onboard_project, onboard_wizard_plan_review
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_contracts.machine_config.schema import GITHUB_AUTH_KIND_USER_AUTHORIZATION


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", "trunk")
    return root


@pytest.fixture
def github(monkeypatch):
    config = {}
    monkeypatch.setattr(
        onboard_publication.machine_config, "github_config", lambda _path: config
    )
    return config


def _connect(github, monkeypatch):
    github.update(
        {
            "web_url": "https://github.com",
            "authorization": {
                "kind": GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "status": "authorized",
                "refresh_credential_ref": "/unused/credential.json",
            },
        }
    )
    monkeypatch.setattr(
        onboard_publication.github_credentials.credential_store,
        "read_credential_document",
        lambda _path: {},
    )


def _review(inputs, config_path):
    mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    plan = onboard_report.build_plan(
        config_path,
        "prod",
        "https://api.example",
        {},
        {},
        "quick",
        project_mode=mode,
        project_inputs=inputs,
        machine_github={"choice": "skip"},
    )
    return onboard_wizard_plan_review.classify_plan(
        {"project_mode": mode, "plan": plan}
    )


def test_review_names_connected_remote_and_branch(
    checkout, tmp_path, github, monkeypatch
):
    _git(
        checkout, "remote", "add", "destination", "https://github.com/other/project.git"
    )
    _git(checkout, "config", "branch.trunk.remote", "destination")
    _connect(github, monkeypatch)
    lines = _review(
        {
            "checkout": str(checkout),
            "default_branch": "trunk",
            "github_adoption": "disabled",
        },
        tmp_path / "config.json",
    )
    assert "Commit Yoke setup and push to destination trunk" in lines["repo"]
    assert all("Bind this project" not in line for line in lines["core"])


def test_review_disconnected_github_names_later_push(checkout, tmp_path, github):
    _git(checkout, "remote", "add", "origin", "https://github.com/other/project.git")
    lines = _review(
        {
            "checkout": str(checkout),
            "default_branch": "trunk",
            "github_adoption": "disabled",
        },
        tmp_path / "config.json",
    )
    assert (
        "Commit Yoke setup and try to push with your own git credentials; "
        "otherwise commit locally, not pushed because GitHub is not connected "
        "(push later with: git push origin trunk)"
    ) in lines["repo"]
    assert all("Bind this project" not in line for line in lines["core"])


def test_review_no_remote_is_local_only(checkout, tmp_path, github):
    lines = _review(
        {"checkout": str(checkout), "default_branch": "trunk"},
        tmp_path / "config.json",
    )
    assert "Commit locally (no remote)" in lines["repo"]


def test_review_uses_tracking_remote_among_multiple(checkout, tmp_path, github):
    _git(checkout, "remote", "add", "source", "https://github.com/source/project.git")
    _git(checkout, "remote", "add", "mine", "https://github.com/mine/project.git")
    _git(checkout, "config", "branch.trunk.remote", "mine")
    text = onboard_publication.plan_step(
        {"checkout": str(checkout), "default_branch": "trunk"},
        tmp_path / "config.json",
    )["target"]
    assert "git push mine trunk" in text
    _git(checkout, "config", "--unset", "branch.trunk.remote")
    text = onboard_publication.plan_step(
        {"checkout": str(checkout), "default_branch": "trunk"},
        tmp_path / "config.json",
    )["target"]
    assert "publication remote is unresolved" in text


def test_review_missing_authorization_file_is_disconnected(checkout, tmp_path, github):
    _git(checkout, "remote", "add", "origin", "https://github.com/other/project.git")
    github.update(
        {
            "web_url": "https://github.com",
            "authorization": {
                "kind": GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "status": "authorized",
                "refresh_credential_ref": str(tmp_path / "missing.json"),
            },
        }
    )
    text = onboard_publication.plan_step(
        {"checkout": str(checkout), "default_branch": "trunk"},
        tmp_path / "config.json",
    )["target"]
    assert "GitHub is not connected" in text


@pytest.mark.parametrize(
    "url",
    ["git@github.com:other/project.git", "https://github.example/other/project.git"],
)
def test_review_github_origin_forms_need_stored_authorization(
    checkout, tmp_path, github, url
):
    _git(checkout, "remote", "add", "origin", url)
    github["web_url"] = (
        "https://github.example" if "github.example" in url else "https://github.com"
    )
    text = onboard_publication.plan_step(
        {"checkout": str(checkout), "default_branch": "trunk"},
        tmp_path / "config.json",
    )["target"]
    assert "GitHub is not connected" in text


def test_review_future_clone_and_created_remote(tmp_path, github, monkeypatch):
    inputs = {
        "checkout": str(tmp_path / "future"),
        "default_branch": "trunk",
        "remote_url": "https://github.com/source/project.git",
    }
    assert (
        "git push origin trunk"
        in onboard_publication.plan_step(
            inputs,
            tmp_path / "config.json",
        )["target"]
    )
    _connect(github, monkeypatch)
    inputs["publish"] = PublishRequest(
        owner="mine", name="project", user_login="mine", token=None
    )
    assert onboard_publication.plan_step(inputs, tmp_path / "config.json")[
        "target"
    ] == ("Commit Yoke setup and push to origin trunk")


def test_review_rehome_previews_new_origin(checkout, tmp_path, github, monkeypatch):
    _git(
        checkout, "remote", "add", "source", "https://other.example/source/project.git"
    )
    _connect(github, monkeypatch)
    inputs = {
        "checkout": str(checkout),
        "default_branch": "trunk",
        "clone": ClonePlan(
            outcome="make-it-mine",
            publish=PublishRequest(
                owner="mine",
                name="project",
                user_login="mine",
                token=None,
            ),
        ),
    }
    assert onboard_publication.plan_step(inputs, tmp_path / "config.json")[
        "target"
    ] == ("Commit Yoke setup and push to origin trunk")


def test_review_existing_repo_without_remote_can_publish(
    checkout, tmp_path, github, monkeypatch
):
    _connect(github, monkeypatch)
    inputs = {
        "checkout": str(checkout),
        "default_branch": "trunk",
        "publish": PublishRequest(
            owner="mine", name="project", user_login="mine", token=None
        ),
    }
    assert onboard_publication.plan_step(inputs, tmp_path / "config.json")[
        "target"
    ] == ("Commit Yoke setup and push to origin trunk")


def test_review_does_not_contact_github(checkout, tmp_path, github, monkeypatch):
    _git(checkout, "remote", "add", "origin", "https://github.com/other/project.git")
    from yoke_cli.config import credentialed_git

    monkeypatch.setattr(
        credentialed_git,
        "resolve_token",
        lambda *_a, **_k: pytest.fail("Review must not resolve a network token"),
    )
    _review(
        {"checkout": str(checkout), "default_branch": "trunk"}, tmp_path / "config.json"
    )


@pytest.mark.parametrize("target", ["skip", "disabled", ""])
def test_skip_labels_do_not_offer_app_binding(target):
    assert "Bind this project" not in onboard_plan_labels.friendly_line(
        "project-github-auth-choice",
        target,
    )
