"""Browser method-case dispatcher transport seam.

Asserts one case's DB legs use the registered Browser function ids with the
documented target/payload/actor shapes. ``call_dispatcher``
is mocked at the seam — handler behavior is covered by
``runtime/api/test_api_qa_browser_function.py`` and transport routing by
the structured-API adapter's own suite.
"""

from __future__ import annotations

import json
from typing import Any as Any, Dict as Dict, List as List
from unittest import mock as mock

from yoke_core.domain import browser_qa as browser_qa
from yoke_core.domain.browser_qa_steps import (
    _complete_run as _complete_run,
    _record_artifact as _record_artifact,
    _record_run as _record_run,
)
from yoke_contracts.api.function_call import (
    ActorContext as ActorContext,
    FunctionCallResponse,
    FunctionError,
)


def _ok(result: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="x",
        version="v1",
        request_id="r",
        result=result,
    )


def _fail(code: str = "boom") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="x",
        version="v1",
        request_id="r",
        error=FunctionError(code=code, message="nope"),
    )


class TestFetchBrowserContextSeam:
    def test_numeric_id_targets_item_id(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"item_id": 42, "requirements": []})

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            browser_qa._fetch_browser_context(
                "externalwebapp",
                10,
                item_id=42,
                expected_branch="feature-x",
            )

        assert calls[0]["function_id"] == "qa.browser_context.get"
        target = calls[0]["target"]
        assert target.kind == "item"
        assert target.item_id == 42
        assert target.public_ref is None
        assert calls[0]["payload"] == {
            "project": "externalwebapp",
            "requirement_id": 10,
            "expected_branch": "feature-x",
        }

    def test_public_ref_targets_item_ref_with_project(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"item_id": 1732, "requirements": []})

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            browser_qa._fetch_browser_context(
                "externalwebapp",
                10,
                item_id="EXT-1732",
            )

        target = calls[0]["target"]
        assert target.kind == "item"
        assert target.item_id is None
        assert target.public_ref == "EXT-1732"
        assert target.project_id == "externalwebapp"

    def test_deployment_run_targets_the_run(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok(
                {
                    "item_id": None,
                    "deployment_run_id": "run-20260101-001",
                    "requirements": [],
                }
            )

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            browser_qa._fetch_browser_context(
                "externalwebapp",
                10,
                deployment_run_id="run-20260101-001",
            )

        target = calls[0]["target"]
        assert target.kind == "deployment_run"
        assert target.deployment_run_id == "run-20260101-001"
        assert target.item_id is None
        assert target.project_id == "externalwebapp"

    def test_dispatch_failure_raises_with_code(self) -> None:
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            return_value=_fail("not_found"),
        ):
            try:
                browser_qa._fetch_browser_context(
                    "externalwebapp",
                    10,
                    item_id=42,
                )
            except RuntimeError as exc:
                assert "not_found" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

    def test_scenario_surfaces_context_failure_as_error_note(self) -> None:
        with mock.patch.object(
            browser_qa,
            "_fetch_browser_context",
            side_effect=RuntimeError("qa.browser_context.get failed"),
        ):
            result = browser_qa.execute_scenario(
                item_id=42,
                project="externalwebapp",
                requirement_id=10,
            )
        assert result.verdict == "error"
        assert result.note == "context_unavailable"

    def test_scenario_adopts_resolved_item_id_from_context(self) -> None:
        seen: Dict[str, Any] = {}

        def _fake_process(**kwargs):
            seen.update(kwargs)
            from yoke_core.domain.browser_qa_requirement import (
                RequirementOutcome,
            )
            from yoke_core.domain.browser_qa_results import RunResult

            return RequirementOutcome(
                run_result=RunResult(
                    requirement_id=10,
                    qa_kind="plan_case",
                    verdict="",
                ),
                executed=True,
            )

        context = {
            "item_id": 1732,
            "requirements": [
                {
                    "id": 10,
                    "qa_kind": "plan_case",
                    "method_id": "browser-check",
                    "method_config": json.dumps(
                        {"base_url": "http://localhost:9", "steps": [{}]},
                    ),
                }
            ],
        }
        with (
            mock.patch.object(
                browser_qa,
                "_fetch_browser_context",
                return_value=context,
            ),
            mock.patch.object(
                browser_qa,
                "_validate_reachability",
                return_value=None,
            ),
            mock.patch.object(
                browser_qa,
                "_ensure_daemon_running",
                return_value=None,
            ),
            mock.patch(
                "yoke_core.domain.browser_qa_scenario._process_requirement",
                side_effect=_fake_process,
            ),
        ):
            result = browser_qa.execute_scenario(
                item_id="EXT-1732",
                project="externalwebapp",
                requirement_id=10,
            )
        assert result.executed == 1
        assert seen["subject"] == "EXT-1732"

    def test_scenario_carries_the_deployment_run_subject(self) -> None:
        seen: Dict[str, Any] = {}

        def _fake_process(**kwargs):
            seen.update(kwargs)
            from yoke_core.domain.browser_qa_requirement import (
                RequirementOutcome,
            )
            from yoke_core.domain.browser_qa_results import RunResult

            return RequirementOutcome(
                run_result=RunResult(
                    requirement_id=10,
                    qa_kind="plan_case",
                    verdict="",
                ),
                executed=True,
            )

        context = {
            "item_id": None,
            "deployment_run_id": "run-20260101-001",
            "requirements": [
                {
                    "id": 10,
                    "qa_kind": "plan_case",
                    "method_id": "browser-check",
                    "method_config": json.dumps(
                        {"base_url": "http://localhost:9", "steps": [{}]},
                    ),
                }
            ],
            # A run case is judged against the commit its run was pinned to
            # deliver, so the context carries one.
            "run_source": {"sha": "a" * 40, "branch": "main"},
        }
        with (
            mock.patch.object(
                browser_qa,
                "_fetch_browser_context",
                return_value=context,
            ),
            mock.patch.object(
                browser_qa,
                "_establish_deployment_freshness",
                return_value=(None, "http://localhost:9", "a" * 40),
            ),
            mock.patch.object(
                browser_qa,
                "_validate_reachability",
                return_value=None,
            ),
            mock.patch.object(
                browser_qa,
                "_ensure_daemon_running",
                return_value=None,
            ),
            mock.patch(
                "yoke_core.domain.browser_qa_scenario._process_requirement",
                side_effect=_fake_process,
            ),
        ):
            result = browser_qa.execute_scenario(
                "externalwebapp",
                10,
                deployment_run_id="run-20260101-001",
            )
        assert result.executed == 1
        assert seen["subject"] == "deployment-run-run-20260101-001"

    def test_scenario_refuses_a_case_naming_no_subject(self) -> None:
        result = browser_qa.execute_scenario("externalwebapp", 10)
        assert result.verdict == "error"
        assert result.note == "subject_invalid"
