"""HTTP-boundary actor identity isolation."""

from unittest.mock import patch

from yoke_core.domain import yoke_function_actor_identity as identity_module
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_actor_identity import ActorLookup
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_idempotency_scope import (
    idempotency_payload_checksum,
)
from yoke_core.domain.yoke_function_registry import register, reset_registry_for_tests
from runtime.api.domain.test_yoke_function_actor_identity_dispatch import (
    _IntegrationBase,
    _Recorder,
    _Req,
    _Resp,
    _make_request,
    _ok_handler,
    _warning_handler,
)


def test_empty_envelope_session_with_empty_ambient_stays_missing():
    reset_registry_for_tests()
    recorder = _Recorder()
    with (
        patch.object(events_module, "emit_event", recorder),
        patch.object(
            identity_module,
            "_default_actor_id_resolver",
            lambda _sid: ActorLookup(),
        ),
    ):
        register(
            "intg.http.op",
            _ok_handler,
            _Req,
            _Resp,
            stability="stable",
            owner_module="yoke_core.domain.test_actor_identity",
            target_kinds=["item"],
            side_effects=["rows_insert"],
            emitted_event_names=[],
            guardrails=[],
            adapter_status="live",
        )
        with patch.dict(
            "os.environ",
            {"YOKE_SESSION_ID": "server-process-session"},
            clear=False,
        ):
            response = dispatch(
                _make_request(
                    function="intg.http.op",
                    payload_session="",
                ),
                ambient_session_id="",
            )
    reset_registry_for_tests()
    assert not response.success
    assert response.error is not None
    assert response.error.code == "actor_session_missing"


class TestDispatcherProvenanceMarking(_IntegrationBase):
    """Calls from sessions with no harness_sessions row are marked."""

    resolver_lookup = ActorLookup(actor_id=None, session_found=False)

    def test_unregistered_session_marks_called_event(self):
        self._register("intg.mut.ghost", side_effects=["rows_insert"])

        response = dispatch(
            _make_request(
                function="intg.mut.ghost",
                payload_session="ghost-session",
            ),
            ambient_session_id="ghost-session",
        )

        self.assertTrue(response.success)
        context = self._called_events()[0]["kwargs"]["context"]
        self.assertIs(context["provenance_unverified"], True)

    def test_unregistered_session_marks_downstream_degraded(self):
        self._register(
            "intg.warn.ghost",
            handler=_warning_handler,
            side_effects=["rows_insert"],
        )

        response = dispatch(
            _make_request(
                function="intg.warn.ghost",
                payload_session="ghost-session",
            ),
            ambient_session_id="ghost-session",
        )

        self.assertTrue(response.success)
        warning_events = self._called_events("DispatcherDownstreamDegraded")
        self.assertEqual(len(warning_events), 1)
        self.assertIs(
            warning_events[0]["kwargs"]["context"]["provenance_unverified"],
            True,
        )

    def test_unregistered_session_marks_idempotency_replay(self):
        self._register("intg.replay.ghost", side_effects=["rows_insert"])

        request = _make_request(
            function="intg.replay.ghost",
            payload_session="ghost-session",
            actor_id="ghost-actor",
            request_id="r-1",
        )
        stored = (
            {"replayed": True},
            "intg.replay.ghost",
            "ghost-actor",
            "authenticated_actor",
            idempotency_payload_checksum(request),
        )
        with patch.object(
            dispatch_module,
            "_idempotency_lookup",
            return_value=stored,
        ):
            response = dispatch(
                request,
                ambient_session_id="ghost-session",
            )

        self.assertTrue(response.success)
        replay_events = self._called_events("DispatcherIdempotencyReplay")
        self.assertEqual(len(replay_events), 1)
        self.assertIs(
            replay_events[0]["kwargs"]["context"]["provenance_unverified"],
            True,
        )
