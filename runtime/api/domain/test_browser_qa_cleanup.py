"""A failed browser step preserves its evidence and runs declared recovery."""

from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.browser_qa_test_helpers import (
    _patch_external_deps,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain import browser_qa
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)


def _scenario(tmp_path, *, cleanup, cleanup_fails=False):
    calls = []
    actor = {"enabled": True}
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 821)
        req_id = _seed_requirement(
            db_path,
            821,
            "browser-check",
            {
                "steps": [
                    {"action": "navigate", "route": "/actors"},
                    {"action": "wait_for", "target": "#missing"},
                    {"action": "click", "target": "#dependent-one"},
                    {
                        "action": "assert",
                        "target": "#dependent-two",
                        "check": "visible",
                    },
                ],
                "cleanup_steps": cleanup,
            },
        )

        def execute(step, _base_url, artifact_dir, _page_id):
            calls.append(step)
            if step["action"] == "wait_for":
                return {"success": False, "error": "missing_required_element"}
            if step["action"] == "screenshot":
                path = Path(artifact_dir) / "failure.png"
                path.write_bytes(b"PNG")
                return {"success": True, "artifacts": [str(path)]}
            if step.get("target") == "#disable-actor":
                if cleanup_fails:
                    return {"success": False, "error": "disable_refused"}
                actor["enabled"] = False
            return {"success": True, "artifacts": []}

        with ExitStack() as stack:
            for patch in _patch_external_deps(db_path):
                stack.enter_context(patch)
            stack.enter_context(
                mock.patch.object(browser_qa, "_execute_step", side_effect=execute)
            )
            result = browser_qa.execute_scenario(
                project="testproj",
                item_id=821,
                requirement_id=req_id,
                base_url="http://localhost:9999",
            )
    return result.runs[0], calls, actor


def test_failed_wait_stops_dependents_captures_once_and_disables_actor(tmp_path):
    run, calls, actor = _scenario(
        tmp_path,
        cleanup=[
            {"action": "navigate", "route": "/actor-settings"},
            {"action": "click", "target": "#disable-actor"},
        ],
    )
    assert [step["action"] for step in calls] == [
        "navigate",
        "wait_for",
        "screenshot",
        "navigate",
        "click",
    ]
    assert actor["enabled"] is False
    assert run.verdict == "fail"
    assert run.artifact_ids
    assert "step_1:missing_required_element" in run.errors
    assert "cleanup_step" not in run.errors


def test_cleanup_failure_does_not_hide_first_failure(tmp_path):
    run, calls, actor = _scenario(
        tmp_path,
        cleanup=[{"action": "click", "target": "#disable-actor"}],
        cleanup_fails=True,
    )
    assert actor["enabled"] is True
    assert run.verdict == "fail"
    assert run.artifact_ids
    assert run.errors.index("step_1:missing_required_element") < run.errors.index(
        "cleanup_step_0:disable_refused"
    )
    assert len(calls) == 4


def test_cleanup_is_bounded_and_validated_at_authoring():
    config = {
        "steps": [
            {"action": "navigate", "route": "/"},
            {"action": "assert", "target": "body", "check": "visible"},
        ],
        "cleanup_steps": [{"action": "click", "target": "#disable"}] * 6,
    }
    with pytest.raises(QaMethodConfigError, match="1 to 5"):
        validate_method_config("browser-check", config)
