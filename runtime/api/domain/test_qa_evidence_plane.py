"""QA evidence writes run where the universe's artifact store lives.

A ``*-db-admin`` connection is a database door into a universe another build
serves; evidence written through it used to land on the capture machine's
disk, where a hosted reviewer saw only a placeholder. These tests pin the
routing decision and the dispatcher's use of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from yoke_cli.transport import dispatcher
from yoke_contracts import qa_evidence_plane, schema_authority
from yoke_contracts.api.function_call import TargetRef

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"
CONFIG_WITH_PLANE = {
    "connections": {
        ADMIN_ENV: {"transport": "local-postgres", "prod": True},
        SERVED_ENV: {"transport": "https", "api_url": "https://example.test/api"},
    }
}


def _select(
    monkeypatch: pytest.MonkeyPatch, env: str, config: dict[str, Any]
) -> None:
    runtime = qa_evidence_plane.machine_config_runtime
    monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: env)
    monkeypatch.setattr(runtime, "load_config", lambda *_a, **_kw: config)


class TestEvidenceRelayEnv:
    def test_database_door_relays_evidence_to_its_https_plane(self, monkeypatch):
        _select(monkeypatch, ADMIN_ENV, CONFIG_WITH_PLANE)
        for function_id in qa_evidence_plane.EVIDENCE_WRITE_FUNCTIONS:
            assert qa_evidence_plane.evidence_relay_env(function_id) == SERVED_ENV

    def test_other_functions_keep_the_active_connection(self, monkeypatch):
        _select(monkeypatch, ADMIN_ENV, CONFIG_WITH_PLANE)
        assert qa_evidence_plane.evidence_relay_env("qa.run.add") is None

    def test_local_universe_writes_where_it_always_did(self, monkeypatch):
        _select(monkeypatch, "local", {"connections": {}})
        assert qa_evidence_plane.evidence_relay_env("qa.artifact.add") is None

    def test_door_without_its_plane_refuses_with_the_repair(self, monkeypatch):
        _select(
            monkeypatch,
            ADMIN_ENV,
            {"connections": {ADMIN_ENV: {"transport": "local-postgres"}}},
        )
        with pytest.raises(qa_evidence_plane.EvidencePlaneUnresolved) as raised:
            qa_evidence_plane.evidence_relay_env("qa.artifact.presign")
        assert raised.value.code == "evidence_plane_unresolved"
        assert "yoke connection set prod --api-url" in str(raised.value)

    def test_declared_serving_build_is_not_a_door(self, monkeypatch):
        _select(monkeypatch, ADMIN_ENV, CONFIG_WITH_PLANE)
        with schema_authority.serving_build_authority():
            assert qa_evidence_plane.evidence_relay_env("qa.artifact.add") is None


class TestDispatcherRouting:
    def _resolved(self, monkeypatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def resolve(**kwargs: Any) -> None:
            calls.append(kwargs)
            return None

        monkeypatch.setattr(
            dispatcher.https_transport, "resolve_https_connection", resolve
        )
        return calls

    def test_evidence_write_from_a_door_names_the_serving_plane(self, monkeypatch):
        _select(monkeypatch, ADMIN_ENV, CONFIG_WITH_PLANE)
        calls = self._resolved(monkeypatch)
        response = dispatcher.call_dispatcher(
            function_id="qa.artifact.add",
            target=TargetRef(kind="qa_requirement", qa_requirement_id=1),
            payload={},
        )
        assert calls == [{"explicit_env": SERVED_ENV}]
        # The stubbed plane resolves to nothing, so the transport refuses
        # rather than quietly writing through the door.
        assert response.error is not None
        assert response.error.code == "relay_env_unavailable"

    def test_unresolvable_plane_is_a_named_refusal(self, monkeypatch):
        _select(
            monkeypatch,
            ADMIN_ENV,
            {"connections": {ADMIN_ENV: {"transport": "local-postgres"}}},
        )
        response = dispatcher.call_dispatcher(
            function_id="qa.artifact.add",
            target=TargetRef(kind="qa_requirement", qa_requirement_id=1),
            payload={},
        )
        assert response.error is not None
        assert response.error.code == "evidence_plane_unresolved"

    def test_run_writes_stay_on_the_door(self, monkeypatch):
        _select(monkeypatch, ADMIN_ENV, CONFIG_WITH_PLANE)
        calls = self._resolved(monkeypatch)
        seen: list[str] = []

        def local_dispatch(request: Any) -> Any:
            seen.append(request.function)
            return dispatcher._error_response(request, "stub", "stub")

        monkeypatch.setattr(
            dispatcher.local_github_dispatch,
            "call_with_machine_github_authorization",
            lambda request, dispatch, core_available: dispatch(request),
        )
        dispatcher.call_dispatcher(
            function_id="qa.run.add",
            target=TargetRef(kind="qa_requirement", qa_requirement_id=1),
            payload={},
            _local_dispatch=local_dispatch,
        )
        assert calls == [{}]
        assert seen == ["qa.run.add"]
