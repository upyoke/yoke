"""Adapter stubs for deployment-pipeline CI gate tests."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from unittest import mock

from yoke_core.domain import deploy_pipeline_gates

PASSED_RESPONSE = {
    "success": True,
    "result": {"state": "passed"},
}


def ci_response(state: str) -> subprocess.CompletedProcess:
    """Render one typed check-ci adapter response in the given state."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"success": True, "result": {"state": state}}),
        stderr="",
    )


def commit_file(repo, filename: str, content: str) -> str:
    """Commit *content* into *repo* and return the resulting commit sha."""
    (repo / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", filename], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.name=release-ci-test",
            "-c", "user.email=release-ci-test@example.invalid",
            "commit", "-q", "--no-gpg-sign", "-m", f"Update {filename}",
        ],
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@contextmanager
def stub_ci_adapter(
    response=None,
    *,
    stdout: str | None = None,
    returncode: int = 0,
    stderr: str = "",
):
    """Stub CI workflow lookup and the typed GitHub Actions adapter."""
    rendered_stdout = (
        stdout
        if stdout is not None
        else json.dumps(PASSED_RESPONSE if response is None else response)
    )
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=returncode,
                stdout=rendered_stdout,
                stderr=stderr,
            ),
        ) as github_actions,
    ):
        yield github_actions
