"""Reading what a branch names right now, from a checkout's own remote.

This is the single read behind a run's bound-source record. It answers from
the remote rather than a local ref, because a stale local branch would pin a
release to a commit the project no longer considers its trunk tip — and it
refuses rather than returning an empty value, because an empty binding
dispatches a build against nothing.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow_bindings as bindings


CONSUMER = "b" * 40


class TestResolveBranchHeadSha:
    def test_it_returns_the_commit_the_remote_branch_names(self):
        with mock.patch.object(
            bindings, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=f"{CONSUMER}\trefs/heads/main\n",
            ),
        ) as run_cmd:
            sha, error = bindings.resolve_branch_head_sha("/platform", "main")

        assert (sha, error) == (CONSUMER, "")
        assert run_cmd.call_args.args[0] == [
            "git", "-C", "/platform", "ls-remote", "origin", "refs/heads/main",
        ]

    def test_an_unreachable_remote_names_the_branch_it_could_not_read(self):
        with mock.patch.object(
            bindings, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="no such remote",
            ),
        ):
            sha, error = bindings.resolve_branch_head_sha("/platform", "main")

        assert sha == ""
        assert "main" in error and "/platform" in error

    def test_an_empty_answer_is_a_refusal_rather_than_an_empty_binding(self):
        with mock.patch.object(
            bindings, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="   \n",
            ),
        ):
            sha, error = bindings.resolve_branch_head_sha("/platform", "main")

        assert sha == ""
        assert "stale or empty" in error
