"""A merge names the GitHub authority it needs before it starts, and proves
its landed commit under that same authority."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_github_authority as authority_module
from yoke_core.domain import project_github_auth as project_auth
from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain.merge_github_authority import (
    DIRECT_MERGE_ROUTE,
    PULL_REQUEST_MERGE_ROUTE,
    classify_merge_authority,
    merge_reaches_github,
)
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_INSTALLATION,
    GITHUB_AUTHORITY_USER,
)
from yoke_core.engines import merge_worktree
from yoke_core.engines import merge_worktree_pr_rest
from yoke_core.engines import merge_worktree_runner
from yoke_core.engines.merge_worktree import MergeArgs, MergeContext


@pytest.fixture(autouse=True)
def _connected_merge(monkeypatch):
    monkeypatch.setattr(authority_module, "github_merge_enabled", lambda _p: True)


class TestClassification:
    """Each route names one authority and the permission it exercises."""

    def test_direct_merge_is_installation_authorized(self) -> None:
        classified = classify_merge_authority(local_merge=True)
        assert classified.route == DIRECT_MERGE_ROUTE
        assert classified.authority == GITHUB_AUTHORITY_INSTALLATION
        assert classified.user_authorization_required is False
        assert dict(classified.permissions) == {"checks": "read"}
        assert "direct merge" in classified.describe()

    def test_pull_request_merge_requires_user_authorization(self) -> None:
        classified = classify_merge_authority(local_merge=False)
        assert classified.route == PULL_REQUEST_MERGE_ROUTE
        assert classified.authority == GITHUB_AUTHORITY_USER
        assert classified.user_authorization_required is True
        assert dict(classified.permissions) == {"pull_requests": "write"}
        assert "user authorization" in classified.describe()

    def test_only_a_merge_that_leaves_the_machine_needs_admitting(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(authority_module.git, "has_remote", lambda _root: True)
        assert merge_reaches_github(
            local_merge=False,
            standalone=False,
            repo_root="/repo",
            project="yoke",
        )
        assert merge_reaches_github(
            local_merge=True,
            standalone=True,
            repo_root="/repo",
            project="yoke",
        )
        assert not merge_reaches_github(
            local_merge=True,
            standalone=False,
            repo_root="/repo",
            project="yoke",
        )

    def test_a_remoteless_checkout_never_reaches_github(self, monkeypatch) -> None:
        monkeypatch.setattr(authority_module.git, "has_remote", lambda _root: False)
        assert not merge_reaches_github(
            local_merge=True,
            standalone=True,
            repo_root="/repo",
            project="yoke",
        )


class TestPostPushProofUsesTheMergesAuthority:
    """The proof after a landed merge asks for the authority that landed it."""

    def test_check_runs_are_read_under_the_authority_it_is_given(
        self,
        monkeypatch,
    ) -> None:
        seen: dict[str, object] = {}

        def _resolve(_ctx, *, required_permissions, required_authority):
            seen["permissions"] = dict(required_permissions)
            seen["authority"] = required_authority
            return SimpleNamespace(repo="upyoke/yoke", token="tok")

        monkeypatch.setattr(post_push, "resolve_auth", _resolve)
        monkeypatch.setattr(
            post_push,
            "request_with_retry",
            lambda _request, **_k: SimpleNamespace(
                body={"total_count": 0, "check_runs": []},
            ),
        )

        runs, error = post_push.read_check_runs(
            "yoke",
            "abc123",
            GITHUB_AUTHORITY_INSTALLATION,
        )

        assert error == ""
        assert runs == ()
        assert seen == {
            "permissions": {"checks": "read"},
            "authority": GITHUB_AUTHORITY_INSTALLATION,
        }

    def test_a_direct_landing_proves_itself_under_installation_authority(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        seen: list[str] = []
        monkeypatch.setattr(post_push.git, "git_out", lambda *_a: "m" * 40)
        monkeypatch.setattr(post_push.git, "publish", lambda *_a: (True, ""))
        monkeypatch.setattr(post_push.git, "has_remote", lambda *_a: False)
        monkeypatch.setattr(merge_boundary.git, "branch_exists", lambda *_a: True)
        monkeypatch.setattr(merge_boundary.git, "head_of", lambda *_a: "c" * 40)
        monkeypatch.setattr(merge_boundary.git, "changed_files", lambda *_a: ("f.py",))
        monkeypatch.setattr(merge_boundary.git, "is_ancestor", lambda *_a: True)
        monkeypatch.setattr(
            merge_boundary, "stamp_merged_at", lambda _item, **_kwargs: None
        )
        # An already-contained branch proves the merge its receipt recorded,
        # not whatever commit the target has since moved to.
        monkeypatch.setattr(
            merge_boundary.receipts,
            "load",
            lambda *_a, **_k: merge_boundary.receipts.MergeReceipt(
                branch="YOK-1",
                target="main",
                commit_sha="c" * 40,
                merge_sha="m" * 40,
            ),
        )
        monkeypatch.setattr(post_push.receipts, "record", lambda *_a, **_k: "")
        monkeypatch.setattr(
            post_push,
            "await_post_push_checks",
            lambda _project, _sha, authority: (
                seen.append(authority) or post_push.PostPushVerdict("no_checks")
            ),
        )

        outcome = merge_boundary.merge_standalone_branch(
            item_id=7,
            branch="YOK-1",
            commit_sha="c" * 40,
            target="main",
            repo_root=str(tmp_path),
            project="yoke",
            local_merge=True,
        )

        assert outcome.ok
        assert seen == [GITHUB_AUTHORITY_INSTALLATION]


class TestAdmissionRunsBeforeTheBranchLands:
    """A direct standalone merge is admitted before it can land anything."""

    def _repo_with_remote(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        for command in (
            ["init", "-q", str(repo)],
            ["-C", str(repo), "config", "user.name", "T"],
            ["-C", str(repo), "config", "user.email", "t@e"],
        ):
            subprocess.run(["git", *command], check=True, capture_output=True)
        (repo / "README.md").write_text("init\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "README.md"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
            check=True,
            capture_output=True,
        )
        return repo

    def test_unauthorized_direct_merge_refuses_before_any_merge_work(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        repo = self._repo_with_remote(tmp_path)
        messages: list[str] = []
        ctx = MergeContext(args=MergeArgs(branch="YOK-1"), project="yoke")
        ctx.repo_root = str(repo)
        ctx.worktree_path = str(repo)
        ctx.yoke_repo_root = str(repo)

        monkeypatch.setattr(
            merge_worktree,
            "_print",
            lambda msg="", err=False: messages.append(msg),
        )
        monkeypatch.setattr(merge_worktree, "validate_args", lambda _args: None)
        monkeypatch.setattr(merge_worktree, "resolve_context", lambda _args: ctx)
        monkeypatch.setattr(
            merge_worktree,
            "preflight_checks",
            lambda _ctx: pytest.fail("admission must refuse before merge work"),
        )

        def _unauthorized(*_a, **_k):
            raise project_auth.UserAuthorizationUnavailable(
                "yoke",
                "local GitHub App user authorization is unavailable",
            )

        monkeypatch.setattr(
            merge_worktree_pr_rest,
            "resolve_project_github_auth",
            _unauthorized,
        )

        exit_code = merge_worktree_runner.run(
            MergeArgs(branch="YOK-1", local_merge=True, standalone=True),
        )

        assert exit_code == 1
        refusal = "\n".join(messages)
        assert "user_authorization_unavailable" in refusal
        assert "Requires: direct merge" in refusal
