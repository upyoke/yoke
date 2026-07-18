"""Browser QA — dispatcher transport seam.

Asserts the orchestrator's DB legs are exactly the four browser-QA
function ids with the documented target/payload shapes. ``call_dispatcher``
is mocked at the seam — handler behavior is covered by
``runtime/api/test_api_qa_browser_function.py`` and transport routing by
the structured-API adapter's own suite.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest import mock

from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_steps import (
    _complete_run,
    _record_artifact,
    _record_run,
)
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


def _ok(result: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="x", version="v1", request_id="r", result=result,
    )


def _fail(code: str = "boom") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False, function="x", version="v1", request_id="r",
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
            browser_qa._fetch_browser_context(42, "externalwebapp", "feature-x")

        assert calls[0]["function_id"] == "qa.browser_context.get"
        target = calls[0]["target"]
        assert target.kind == "item"
        assert target.item_id == 42
        assert target.item_ref is None
        assert calls[0]["payload"] == {
            "project": "externalwebapp", "expected_branch": "feature-x",
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
            browser_qa._fetch_browser_context("EXT-1732", "externalwebapp")

        target = calls[0]["target"]
        assert target.kind == "item"
        assert target.item_id is None
        assert target.item_ref == "EXT-1732"
        assert target.project_id == "externalwebapp"

    def test_dispatch_failure_raises_with_code(self) -> None:
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            return_value=_fail("not_found"),
        ):
            try:
                browser_qa._fetch_browser_context(42, "externalwebapp")
            except RuntimeError as exc:
                assert "not_found" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

    def test_scenario_surfaces_context_failure_as_error_note(self) -> None:
        with mock.patch.object(
            browser_qa, "_fetch_browser_context",
            side_effect=RuntimeError("qa.browser_context.get failed"),
        ):
            result = browser_qa.execute_scenario(item_id=42, project="externalwebapp")
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
                    requirement_id=10, qa_kind="browser_smoke", verdict="",
                ),
                executed=True,
            )

        context = {
            "item_id": 1732,
            "requirements": [{
                "id": 10, "qa_kind": "browser_smoke",
                "success_policy": json.dumps(
                    {"base_url": "http://localhost:9", "steps": [{}]},
                ),
            }],
        }
        with mock.patch.object(
            browser_qa, "_fetch_browser_context", return_value=context,
        ), mock.patch.object(
            browser_qa, "_validate_reachability", return_value=None,
        ), mock.patch.object(
            browser_qa, "_ensure_daemon_running", return_value=None,
        ), mock.patch(
            "yoke_core.domain.browser_qa_scenario._process_requirement",
            side_effect=_fake_process,
        ):
            result = browser_qa.execute_scenario(
                item_id="EXT-1732", project="externalwebapp",
            )
        assert result.executed == 1
        assert seen["item_id"] == 1732


class TestWriteSeam:
    def test_record_run_dispatches_qa_run_add(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"qa_run_id": 77, "requirement_id": 10})

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            run_id = _record_run(10, "browser_smoke", raw_result="{}")

        assert run_id == 77
        assert calls[0]["function_id"] == "qa.run.add"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"] == {
            "executor_type": "browser_substrate",
            "qa_kind": "browser_smoke",
            "raw_result": "{}",
        }

    def test_record_run_failure_degrades_to_none(self) -> None:
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            return_value=_fail(),
        ):
            assert _record_run(10, "browser_smoke") is None

    def test_complete_run_dispatches_qa_run_complete(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"qa_run_id": 77})

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            _complete_run(
                77, 10, verdict="fail",
                execution_status="capture_failed", raw_result="{}",
            )

        assert calls[0]["function_id"] == "qa.run.complete"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"] == {
            "run_id": 77, "verdict": "fail",
            "execution_status": "capture_failed", "raw_result": "{}",
        }

    def test_record_artifact_dispatches_qa_artifact_add(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"qa_artifact_id": 5})

        handle = {
            "backend": "s3", "bucket": "p-prod-artifacts",
            "key": "qa-artifacts/p/42/77/home.png",
        }
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            art_id = _record_artifact(
                77, 10, "screenshot", "image/png", handle, "{}",
            )

        assert art_id == 5
        assert calls[0]["function_id"] == "qa.artifact.add"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"]["artifact_handle"] == handle
