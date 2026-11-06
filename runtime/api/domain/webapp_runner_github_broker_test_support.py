# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import hashlib

from pathlib import Path

import shutil

import subprocess

import textwrap

import pytest

from runtime.api.domain.webapp_runner_broker_test_support import (
    _write_node_fixture,
)


def _environment(mode: str) -> str:
    return textwrap.dedent(f"""
        Object.assign(process.env, {{
          BROKER_MODE: "{mode}",
          GITHUB_API_URL: "https://api.github.com",
          GITHUB_APP_ISSUER: "Iv1.runner",
          GITHUB_INSTALLATION_ID: "123456",
          GITHUB_REPOSITORY_ID: "789012",
          GITHUB_REPO_OWNER: "acme",
          GITHUB_REPO_NAME: "service",
          GITHUB_PRIVATE_KEY_SECRET_ARN:
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:app-AbCdEf",
          RUNNER_ASG_NAME: "runner-asg",
          RUNNER_ARCHITECTURE: "x64",
          RUNNER_PREFIX: "yoke-github-actions-",
          RUNNER_LABELS: "self-hosted,Linux,X64,yoke-github-actions",
          DESIRED_RUNNER_COUNT: "1",
          IDLE_MINUTES: "30",
          LIFECYCLE_STATE_PARAMETER: "/fleet/lifecycle-state",
          QUEUE_ACTIVITY_PARAMETER: "/fleet/queue-activity",
          RUNNER_PROGRESS_PARAMETER: "/fleet/runner-progress",
          RUNNER_COMPLETION_PARAMETER: "/fleet/runner-completion",
          BOOTSTRAP_MARKER_PREFIX: "/fleet/bootstrap",
          BOOTSTRAP_TIMEOUT_MINUTES: "30",
          READY_GRACE_MINUTES: "5",
          MAX_BOOTSTRAP_RETRIES: "3",
          JOB_EVENT_TIMEOUT_MINUTES: "360",
        }});
    """)


def _run_driver(tmp_path: Path, body: str) -> dict:
    driver = tmp_path / "driver.mjs"
    driver.write_text(textwrap.dedent(body))
    result = subprocess.run(
        ["node", str(driver)],
        cwd=tmp_path,
        text=True,
        check=True,
        capture_output=True,
    )
    assert "installation-secret" not in result.stdout
    return json.loads(result.stdout)
