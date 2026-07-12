"""Clone outcome resume and post-mutation App discovery reconciliation."""

from __future__ import annotations

import io
import json
from pathlib import Path
import urllib.error

import pytest

from runtime.api.cli.test_yoke_operations_cli_project_clone_outcome import (
    _clone_into,
    _git,
    _seed_bare_source,
)
from yoke_cli.config import github_publish_transport
from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import project_onboard, project_onboard_clone
from yoke_cli.config.project_publish_support import PublishRequest


@pytest.fixture(autouse=True)
def _local_git_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clone,
        "run_git",
        lambda root, *args, **_kwargs: _git(root, *args),
    )


class _ResumeUrlopen:
    """Mocks the GitHub REST seam so the real create_repo runs its 422 resume.

    The create POST answers 422 (name already exists); the repo GET answers the
    existing summary; the commits probe answers 409 (empty). The real re-home
    then re-pushes against the local bare new-origin. git itself is a subprocess
    and never touches this mock.
    """

    def __init__(self) -> None:
        self.paths: list[tuple[str, str]] = []

    def __call__(self, request, timeout: float = 0.0):
        url_path = request.full_url.split("?", 1)[0]
        self.paths.append((request.get_method(), url_path))
        if url_path.endswith("/user/repos"):
            raise self._error(request.full_url, 422, "name already exists")
        if url_path.endswith("/octocat/widgets/commits"):
            raise self._error(request.full_url, 409, "Git Repository is empty")
        if url_path.endswith("/repos/octocat/widgets"):
            return self._ok(
                {
                    "full_name": "octocat/widgets",
                    "private": True,
                    "default_branch": "main",
                }
            )
        raise AssertionError(f"unexpected GitHub call: {request.full_url}")

    @staticmethod
    def _ok(payload: dict):
        class _Resp(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Resp(json.dumps(payload).encode("utf-8"))

    @staticmethod
    def _error(url: str, status: int, message: str) -> urllib.error.HTTPError:
        body = io.BytesIO(json.dumps({"message": message}).encode("utf-8"))
        return urllib.error.HTTPError(url, status, message, {}, body)


def test_make_it_mine_resume_reuses_created_repo_and_repushes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # End-to-end resume: the repo was created by a prior run (push hadn't
    # landed), so this run's create POST 422s. The real create_repo reuses the
    # empty repo and the idempotent re-home re-pushes — onboarding completes
    # instead of aborting on "name already exists".
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    fake = _ResumeUrlopen()
    monkeypatch.setattr(github_publish_transport, "_urlopen", fake)
    monkeypatch.setattr(
        project_onboard_clone, "https_remote", lambda repo, **_: str(new_origin)
    )

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=False,
        publish=PublishRequest(
            owner="octocat",
            name="widgets",
            user_login="octocat",
            token="ghs_x",
            administration_allowed=True,
        ),
    )
    outcome = project_onboard._apply_clone_outcome(
        target,
        remote_url=str(source),
        default_branch="main",
        plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    assert outcome.branch == "main"
    # The repo was adopted on the 422 resume path, so repo_reused is surfaced.
    assert outcome.repo_reused is True
    # The reuse probe ran: create POST -> GET repo -> GET commits.
    assert fake.paths[0][0] == "POST"
    assert fake.paths[0][1].endswith("/user/repos")
    assert any(p[1].endswith("/repos/octocat/widgets") for p in fake.paths)
    assert any(p[1].endswith("/octocat/widgets/commits") for p in fake.paths)
    # The idempotent re-home re-pushed: origin points at the reused repo and the
    # branch actually landed on it.
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert "main" in _git(new_origin, "branch", "--list")


@pytest.mark.parametrize(
    "outcome_name",
    [
        clone.CLONE_OUTCOME_MAKE_IT_MINE,
        clone.CLONE_OUTCOME_FORK,
    ],
)
def test_import_refreshes_app_discovery_for_every_new_repo_outcome(
    outcome_name: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    refreshed: list[str] = []
    result = project_onboard_clone.CloneApplyResult(
        github_repo="octocat/widgets",
        branch="main",
    )
    monkeypatch.setattr(
        project_onboard.project_onboard_apply, "ensure_git_available", lambda: None
    )
    monkeypatch.setattr(project_onboard, "_resumable_clone", lambda *_a, **_k: False)
    monkeypatch.setattr(
        project_onboard, "_apply_clone_outcome", lambda *_a, **_k: result
    )
    monkeypatch.setattr(
        project_onboard.progress_steps,
        "record_mutated_repository",
        lambda _adoption, repo, _config, **_kwargs: refreshed.append(repo),
    )
    monkeypatch.setattr(
        project_onboard,
        "dispatch",
        lambda *_a, **_k: {"project": {"id": 9, "slug": "widgets"}},
    )
    monkeypatch.setattr(
        project_onboard.project_onboard_apply,
        "finish_after_dispatch",
        lambda **_kwargs: {"applied": True},
    )
    monkeypatch.setattr(
        project_onboard, "_finish_github_binding", lambda *_a, **_k: None
    )

    project_onboard.import_project(
        remote_url="https://github.com/acme/widgets.git",
        checkout=tmp_path / outcome_name,
        slug="widgets",
        name="Widgets",
        org=None,
        github_repo="octocat/widgets",
        default_branch="main",
        public_item_prefix="WID",
        github_adoption_choice="app-binding",
        config_path=None,
        apply=True,
        clone=clone.ClonePlan(outcome=outcome_name, fallback_token="ghu_short"),
    )

    assert refreshed == ["octocat/widgets"]
