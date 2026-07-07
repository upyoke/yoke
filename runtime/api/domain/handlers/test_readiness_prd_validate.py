"""Handler coverage for readiness.prd_validate.run."""

from __future__ import annotations

import pytest

from yoke_core.domain import prd_validate
from yoke_core.domain.handlers import readiness
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain import yoke_function_registry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload=None, *, item_id: int = 42) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="readiness.prd_validate.run",
        actor=ActorContext(session_id="sess-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _patch_prd(monkeypatch: pytest.MonkeyPatch, report: prd_validate.Report):
    calls = {}

    def resolve_body(item_ref, body_text):
        calls["resolve_body"] = (item_ref, body_text)
        return "body text", item_ref

    def validate_prd(body, item_label):
        calls["validate_prd"] = (body, item_label)
        return report

    def print_report(item_label, rendered_report):
        calls["print_report"] = (item_label, rendered_report)
        print(f"rendered {item_label}")

    monkeypatch.setattr(prd_validate, "resolve_body", resolve_body)
    monkeypatch.setattr(prd_validate, "validate_prd", validate_prd)
    monkeypatch.setattr(
        "yoke_core.domain.prd_validate_render.print_report",
        print_report,
    )
    return calls


def test_prd_validate_handler_reuses_domain_validator(monkeypatch):
    report = prd_validate.Report(pass_count=1, passed=["PASS: PRD-1 ok"])
    calls = _patch_prd(monkeypatch, report)

    outcome = readiness.handle_prd_validate(_request())

    assert outcome.primary_success is True
    assert calls["resolve_body"] == ("YOK-42", None)
    assert calls["validate_prd"] == ("body text", "YOK-42")
    assert outcome.result_payload["passed"] is True
    assert outcome.result_payload["passed_checks"] == ["PASS: PRD-1 ok"]
    assert outcome.result_payload["report_text"] == "rendered YOK-42"


def test_prd_validate_handler_fails_gate_without_error(monkeypatch):
    report = prd_validate.Report(
        fail_count=1,
        failures=["FAIL: PRD-2 missing requirements"],
    )
    _patch_prd(monkeypatch, report)

    outcome = readiness.handle_prd_validate(_request())

    assert outcome.primary_success is False
    assert outcome.error is None
    assert outcome.result_payload["passed"] is False
    assert outcome.result_payload["failures"] == [
        "FAIL: PRD-2 missing requirements"
    ]


def test_prd_validate_strict_treats_warnings_as_failure(monkeypatch):
    report = prd_validate.Report(
        pass_count=1,
        warn_count=1,
        passed=["PASS: PRD-1 ok"],
        warnings=["WARN: PRD-3 maybe vague"],
    )
    _patch_prd(monkeypatch, report)

    outcome = readiness.handle_prd_validate(_request({"strict": True}))

    assert outcome.primary_success is False
    assert outcome.result_payload["strict"] is True
    assert outcome.result_payload["warnings"] == ["WARN: PRD-3 maybe vague"]


def test_prd_validate_registration_is_read_only() -> None:
    yoke_function_registry.reset_registry_for_tests()
    try:
        init_register.register_all_handlers()
        entry = yoke_function_registry.lookup("readiness.prd_validate.run")
    finally:
        yoke_function_registry.reset_registry_for_tests()

    assert entry is not None
    assert entry.target_kinds == ("item",)
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
