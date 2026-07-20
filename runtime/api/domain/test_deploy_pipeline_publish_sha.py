"""Immutable source resolution for the github-actions-workflow executor.

The publish must ship the deployment run's saved commit even when the local
checkout or remote branch moves before a resume. Historical version lineages
resolve only through their annotated release tag's peeled commit.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow
from yoke_core.domain import deploy_product_source


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    return root


def _mock_checkout(tmp_path) -> str:
    """A path that passes the checkout-existence preflight; git is mocked."""
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    return str(checkout)


def _commit(repo, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.name=deploy-preflight-test",
            "-c", "user.email=deploy-preflight-test@example.invalid",
            "commit", "-q", "-m", name, "--no-gpg-sign",
        ],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return head.stdout.strip()


class TestPublishShaFromDeployedRef:
    @staticmethod
    def _run_cmd_stub(*, ls_remote_sha: str, local_head_sha: str = "localunpushed"):
        def _fake(cmd, *args, **kwargs):
            if "ls-remote" in cmd:
                out = f"{ls_remote_sha}\trefs/heads/x\n" if ls_remote_sha else ""
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out)
            # Any local rev-parse HEAD path — must NOT be what gets published.
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=f"{local_head_sha}\n",
            )
        return _fake

    def test_publishes_saved_run_lineage_after_remote_branch_moves(self, tmp_path):
        gh_calls = []
        ci_gate = mock.Mock(return_value=(True, ""))
        saved_sha = "a" * 40
        moved_main_sha = "b" * 40

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="run-9\n")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", ci_gate,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            side_effect=self._run_cmd_stub(
                ls_remote_sha=moved_main_sha, local_head_sha="localunpushed",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {"source_sha": "{head_sha}"},
                    "ref": "main",
                    "reconcile_by_head_sha": False,
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/repo",
                project="yoke",
                project_repo_path=_mock_checkout(tmp_path),
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                release_lineage=saved_sha,
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert f"source_sha={saved_sha}" in trigger
        assert f"source_sha={moved_main_sha}" not in trigger
        assert "source_sha=localunpushed" not in trigger
        assert ci_gate.call_args.kwargs["head_sha"] == saved_sha

    def test_correlated_workflow_gets_release_sized_timeout(self, tmp_path):
        poll = mock.Mock(return_value=(0, "completed: success"))
        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate",
            return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            side_effect=self._run_cmd_stub(ls_remote_sha="deadbeef"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="run-9\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions", poll,
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "release.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "reconcile_by_head_sha": False,
                },
                name="hosted-release", run_id="run-test", member_items=[],
                github_repo="owner/repo", project="yoke",
                project_repo_path=_mock_checkout(tmp_path),
                timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40,
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        assert poll.call_args.args[2] == 120 * 60

    def test_fail_fast_when_run_has_no_release_lineage(self):
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            side_effect=self._run_cmd_stub(ls_remote_sha=""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {"source_sha": "{head_sha}"},
                    "ref": "stage",
                    "reconcile_by_head_sha": False,
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/repo",
                project="yoke",
                project_repo_path="/repo",
                timeout_min=30,
                fresh=False,
                gate_branch="stage",
                release_lineage="",
                sd="/tmp/sd",
            )

        assert rc == 1
        assert "immutable release_lineage" in diag
        # The doomed publish is never dispatched.
        assert not [c for c in gh_calls if c and c[0] == "trigger"]

    def test_version_lineage_resolves_annotated_tag_peeled_commit(self):
        tag_object = "c" * 40
        tag_commit = "d" * 40
        version = "v0.1.1+launch.51"
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                f"{tag_object}\trefs/tags/{version}\n"
                f"{tag_commit}\trefs/tags/{version}^{{}}\n"
            ),
        )
        with mock.patch.object(
            deploy_pipeline_github_workflow,
            "_run_cmd",
            return_value=result,
        ) as run_cmd:
            sha, error = (
                deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                    version,
                    "/repo",
                    "main",
                )
            )

        assert (sha, error) == (tag_commit, "")
        run_cmd.assert_called_once_with([
            "git", "-C", "/repo", "ls-remote", "origin",
            f"refs/tags/{version}", f"refs/tags/{version}^{{}}",
        ])

    def test_version_lineage_refuses_missing_or_lightweight_tag(self):
        version = "v0.1.1+launch.51"
        for stdout in (
            "",
            f"{'c' * 40}\trefs/tags/{version}\n",
        ):
            with mock.patch.object(
                deploy_pipeline_github_workflow,
                "_run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=stdout,
                ),
            ):
                sha, error = (
                    deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                        version,
                        "/repo",
                        "main",
                    )
                )

            assert sha == ""
            assert "annotated release-tag commit" in error

    def test_commit_lineage_must_exist_in_the_project_repository(self, tmp_path):
        repo = _init_repo(tmp_path / "checkout")
        _commit(repo, "seed")
        fabricated_sha = "f" * 40

        sha, error = (
            deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                fabricated_sha,
                str(repo),
                "main",
            )
        )

        assert sha == ""
        assert fabricated_sha in error
        assert "available from the project repository" in error
        assert str(repo) in error
        assert "even after fetching origin" in error

    def test_commit_lineage_does_not_follow_the_environment_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "checkout")
        saved_sha = _commit(repo, "seed")
        _commit(repo, "branch-moved-past-the-saved-commit")

        sha, error = (
            deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                saved_sha,
                str(repo),
                "a-different-environment-branch",
            )
        )

        assert (sha, error) == (saved_sha, "")

    def test_commit_lineage_names_a_missing_checkout_and_its_source(self, tmp_path):
        gone = tmp_path / "removed-worktree"

        sha, error = (
            deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                "a" * 40,
                str(gone),
                "main",
            )
        )

        assert sha == ""
        assert "missing or not a git checkout" in error
        assert str(gone) in error
        assert "machine-config" in error

    def test_commit_lineage_recovers_pushed_commits_with_a_full_fetch(self, tmp_path):
        origin = _init_repo(tmp_path / "origin")
        _commit(origin, "seed")
        # GitHub-shaped server behavior: refuse sha-addressed wants so only
        # the plain ref fetch can retrieve commits pushed after the clone.
        for key in (
            "uploadpack.allowanysha1inwant",
            "uploadpack.allowreachablesha1inwant",
        ):
            subprocess.run(
                ["git", "-C", str(origin), "config", key, "false"],
                check=True,
            )
        consumer = tmp_path / "consumer"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(consumer)], check=True
        )
        pushed_later_sha = _commit(origin, "pushed-later")

        error = deploy_pipeline_github_workflow._verify_release_sha_in_checkout(
            pushed_later_sha,
            str(consumer),
            "main",
        )

        assert error == ""

    def test_explicit_image_pin_resolves_in_product_checkout(self, tmp_path):
        gh_calls = []
        full_commit = "a" * 40

        def _fake_gh(*args, **kwargs):
            gh_calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args=args, returncode=0,
                stdout="run-9\n" if args[0] == "trigger" else "",
            )

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate",
            return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            side_effect=self._run_cmd_stub(ls_remote_sha="deployhead"),
        ), mock.patch.object(
            deploy_product_source, "resolve_product_commit",
            return_value=full_commit,
        ) as resolve, mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions",
            side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {"source_sha": "{head_sha}"},
                    "ref": "main", "reconcile_by_head_sha": False,
                },
                name="distribution-publish", run_id="run-test", member_items=[],
                github_repo="deploy-owner/workflows", project="platform",
                project_repo_path=_mock_checkout(tmp_path),
                product_repo_path="/product",
                image_tag="abc123def456", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40,
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        resolve.assert_called_once_with("/product", "abc123def456")
        trigger = next(call for call in gh_calls if call[0][0] == "trigger")
        assert f"source_sha={full_commit}" in trigger[0]
        assert trigger[1]["project"] == "platform"
