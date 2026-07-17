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

    def test_publishes_saved_run_lineage_after_remote_branch_moves(self):
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
                project_repo_path="/repo",
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

    def test_correlated_workflow_gets_release_sized_timeout(self):
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
                project_repo_path="/repo", timeout_min=30, fresh=False,
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

    def test_commit_lineage_must_be_reachable_from_remote_gate_branch(self):
        fabricated_sha = "f" * 40
        with mock.patch.object(
            deploy_pipeline_github_workflow,
            "_run_cmd",
            side_effect=[
                subprocess.CompletedProcess(args=[], returncode=0, stdout=""),
                subprocess.CompletedProcess(args=[], returncode=1, stdout=""),
            ],
        ):
            sha, error = (
                deploy_pipeline_github_workflow._resolve_release_lineage_sha(
                    fabricated_sha,
                    "/repo",
                    "main",
                )
            )

        assert sha == ""
        assert fabricated_sha in error
        assert "reachable from origin/main" in error

    def test_explicit_image_pin_resolves_in_product_checkout(self):
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
                project_repo_path="/deploy-owner", product_repo_path="/product",
                image_tag="abc123def456", timeout_min=30, fresh=False,
                gate_branch="main", release_lineage="a" * 40,
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        resolve.assert_called_once_with("/product", "abc123def456")
        trigger = next(call for call in gh_calls if call[0][0] == "trigger")
        assert f"source_sha={full_commit}" in trigger[0]
        assert trigger[1]["project"] == "platform"
