"""Keep every test off the environment and CI job running the suite.

The source runner starts pytest with ``UV_PROJECT_ENVIRONMENT`` naming the
checkout's own ``.venv``. A test that inherits it and runs ``uv sync`` or
``uv run`` for a fixture project installs that fixture's lock into the
running environment, removing every package the suite needs mid-run.

Under GitHub Actions the job's command files (``GITHUB_STEP_SUMMARY``,
``GITHUB_OUTPUT``, ``GITHUB_ENV``, ``GITHUB_PATH``) are inherited the same
way, and code under test that reports to them writes the real job's summary
and outputs. Each test therefore starts without any of these; a test that
exercises them sets its own.
"""

from __future__ import annotations

import pytest

#: Variables that point a test at the running suite's own environment or job.
RUNNING_ENVIRONMENT_VARIABLES = (
    "UV_PROJECT_ENVIRONMENT",
    "GITHUB_STEP_SUMMARY",
    "GITHUB_OUTPUT",
    "GITHUB_ENV",
    "GITHUB_PATH",
)


@pytest.fixture(autouse=True)
def _isolate_running_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RUNNING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
