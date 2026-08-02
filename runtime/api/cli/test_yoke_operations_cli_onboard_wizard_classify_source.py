"""Source-choice classification coverage for onboarding plans."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402


def test_classify_plan_threads_project_name_into_source_choice() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
        "plan": {
            "project": {"name": "ExternalWebapp"},
            "steps": [
                {
                    "action": "project-source-choice",
                    "target": onboard_project.PROJECT_MODE_CREATE_REPO,
                }
            ],
        },
    }
    grouped = steps.classify_plan(plan)
    assert grouped["core"] == [
        "Record ExternalWebapp in the Yoke core database as a new project"
    ]
