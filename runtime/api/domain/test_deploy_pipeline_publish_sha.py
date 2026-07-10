"""``source_sha`` resolution coverage for the github-actions-workflow executor
(sibling of :mod:`test_deploy_pipeline_dispatcher`, 350-line cap split).

The publish must ship the deployed branch's remote HEAD, never the local
working-tree HEAD — an unpushed/diverged local commit would die at
``git checkout`` in the dispatched workflow ("reference is not a tree").
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

    def test_publishes_deployed_ref_not_local_head(self):
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="run-9\n")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            side_effect=self._run_cmd_stub(
                ls_remote_sha="deadbeefcafe0000", local_head_sha="localunpushed",
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
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        trigger = next(c for c in gh_calls if c and c[0] == "trigger")
        assert "source_sha=deadbeefcafe0000" in trigger
        assert "source_sha=localunpushed" not in trigger

    def test_fail_fast_when_deploy_branch_absent_from_remote(self):
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
                sd="/tmp/sd",
            )

        assert rc == 1
        assert "stage" in diag and "remote" in diag
        # The doomed publish is never dispatched.
        assert not [c for c in gh_calls if c and c[0] == "trigger"]

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
                    "inputs": {"source_sha": "{head_sha}"},
                    "ref": "main", "reconcile_by_head_sha": False,
                },
                name="distribution-publish", run_id="run-test", member_items=[],
                github_repo="deploy-owner/workflows", project="platform",
                project_repo_path="/deploy-owner", product_repo_path="/product",
                image_tag="abc123def456", timeout_min=30, fresh=False,
                gate_branch="main", sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        resolve.assert_called_once_with("/product", "abc123def456")
        trigger = next(call for call in gh_calls if call[0][0] == "trigger")
        assert f"source_sha={full_commit}" in trigger[0]
        assert trigger[1]["project"] == "platform"
