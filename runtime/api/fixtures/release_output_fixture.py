"""The pytest fixture release-output checks share, registered as a plugin.

It lives apart from the helpers it calls because a module pytest loads as a
plugin must not also be imported directly: the import wins the race, pytest
cannot rewrite its assertions, and every test importing a helper from it pays
a warning. Helpers are imported; this is registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.release_output_source import (
    insert_flow,
    insert_run,
    project_slug,
    release_output_repository,
)
from yoke_core.domain import deployment_run_carried_work_source


@pytest.fixture
def release_source(test_db: Any, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """One repository, one flow, and the run whose promotion wrote the pin."""
    repo, baseline, pin, maintenance = release_output_repository(tmp_path)
    insert_flow(test_db, "release-output-flow")
    insert_run(
        test_db,
        "run-release-output-001",
        baseline,
        flow_id="release-output-flow",
        status="succeeded",
        created_at="2026-09-19T00:01:00Z",
        completed_at="2026-09-19T00:02:00Z",
    )
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    return {
        "repo": repo,
        "baseline": baseline,
        "pin": pin,
        "maintenance": maintenance,
        "producer": "run-release-output-001",
        "project": project_slug(test_db),
    }


__all__ = ["release_source"]
