"""Lane preparation refuses unreadable test environment declarations."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import qa_environment_declaration as declaration
from yoke_core.domain.worktree_provision import provision_worktree_test_environment


def test_preparation_reports_declared_environment_read_failure(monkeypatch, tmp_path):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return FunctionCallResponse(
            success=False, function=kwargs["function_id"], version="v1",
            error=FunctionError(code="unavailable", message="test settings unavailable"),
        )

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", dispatch,
    )
    # Avoid the process-wide declaration cache so this proves the failed read.
    monkeypatch.setattr(declaration, "_read_settings", declaration._read_settings.__wrapped__)
    error = provision_worktree_test_environment(str(tmp_path), project="sample")

    assert error is not None
    assert "Lane test environment provisioning failed" in error
    assert "test_environment declaration read refused: test settings unavailable" in error
    assert calls[0]["function_id"] == "projects.capability_settings.get"
    assert calls[0]["payload"] == {"project": "sample", "cap_type": "test_environment"}
