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
