"""Regression checks for browser qa persistence transport."""

from __future__ import annotations

from runtime.api.domain.test_browser_qa_transport import (
    ActorContext as ActorContext,
    Any as Any,
    Dict as Dict,
    List as List,
    _complete_run as _complete_run,
    _fail as _fail,
    _ok as _ok,
    _record_artifact as _record_artifact,
    _record_run as _record_run,
    browser_qa as browser_qa,
    mock as mock,
)


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
            run_id = _record_run(10, "plan_case", raw_result="{}")

        assert run_id == 77
        assert calls[0]["function_id"] == "qa.run.add"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"] == {
            "performed_by": "browser_substrate",
            "qa_kind": "plan_case",
            "raw_result": "{}",
        }

    def test_record_run_failure_degrades_to_none(self) -> None:
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            return_value=_fail(),
        ):
            assert _record_run(10, "plan_case") is None

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
                77,
                10,
                verdict="fail",
                execution_status="capture_failed",
                raw_result="{}",
            )

        assert calls[0]["function_id"] == "qa.run.complete"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"] == {
            "run_id": 77,
            "verdict": "fail",
            "execution_status": "capture_failed",
            "raw_result": "{}",
        }

    def test_record_artifact_dispatches_qa_artifact_add(self) -> None:
        calls: List[Dict[str, Any]] = []

        def _capture(**kwargs):
            calls.append(kwargs)
            return _ok({"qa_artifact_id": 5})

        handle = {
            "backend": "s3",
            "bucket": "p-prod-artifacts",
            "key": "qa-artifacts/p/42/77/home.png",
        }
        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            art_id = _record_artifact(
                77,
                10,
                "screenshot",
                "image/png",
                handle,
                "{}",
            )

        assert art_id == 5
        assert calls[0]["function_id"] == "qa.artifact.add"
        assert calls[0]["target"].qa_requirement_id == 10
        assert calls[0]["payload"]["artifact_handle"] == handle

    def test_actor_is_forwarded_to_context_and_writes(self) -> None:
        calls: List[Dict[str, Any]] = []
        actor = ActorContext(actor_id="17", session_id="session-17")

        def _capture(**kwargs):
            calls.append(kwargs)
            if kwargs["function_id"] == "qa.browser_context.get":
                return _ok({"item_id": 42, "requirements": []})
            return _ok({"qa_run_id": 77})

        with mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=_capture,
        ):
            browser_qa._fetch_browser_context(
                "externalwebapp",
                10,
                item_id=42,
                actor=actor,
            )
            _record_run(10, "plan_case", actor=actor)

        assert [call["actor"] for call in calls] == [actor, actor]
