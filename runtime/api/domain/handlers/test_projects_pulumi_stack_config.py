"""Secret-free registered Pulumi stack authorization receipt tests."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers import projects_pulumi_stack_config as handler


class _Connection:
    def close(self) -> None:
        pass


def test_registered_result_never_contains_operator_state(monkeypatch):
    monkeypatch.setattr(handler, "connect", lambda: _Connection())
    monkeypatch.setattr(
        handler,
        "build_pulumi_stack_config",
        lambda *args: {
            "config_schema": 2,
            "project_id": 1,
            "project_slug": "yoke",
            "stack_name": "yoke-infra",
            "stack_kind": "infra",
            "render_values": {"state_bucket": "bucket"},
            "operator_state": {
                "secrets_provider": "sensitive-provider",
                "encrypted_key": "sensitive-key",
            },
            "authority": {},
        },
    )
    request = FunctionCallRequest(
        function="projects.pulumi_stack_config.get",
        actor=ActorContext(actor_id="1", session_id="session"),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", "stack": "yoke-infra"},
    )
    outcome = handler.handle_pulumi_stack_config_get(request)
    encoded = json.dumps(outcome.result_payload, sort_keys=True)
    assert outcome.primary_success is True
    assert outcome.result_payload["materialization_authorized"] is True
    assert "operator_state" not in outcome.result_payload
    assert "sensitive-provider" not in encoded
    assert "sensitive-key" not in encoded
