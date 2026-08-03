"""Project GitHub auth resolves over a control plane the client cannot open.

A merge, resync, or label sync driven from an https-connected machine has no
local Postgres, so the binding-state read and the sync receipt must relay
rather than opening a bare connection. Opening one is the failure these
tests exist to catch: it raises before the operation starts.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import project_github_auth_state as state_reader
from yoke_core.domain import project_github_sync_receipt as receipt


class NoLocalPostgres(RuntimeError):
    """What opening a local connection raises on an https control plane."""


@pytest.fixture
def no_local_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every direct connection attempt fail, as https does."""
    def refuse(*_args, **_kwargs):
        raise NoLocalPostgres(
            "connected env 'prod' (transport https) has no local Postgres"
        )

    monkeypatch.setattr(state_reader, "connect", refuse)
    monkeypatch.setattr(receipt, "connect", refuse)


@pytest.fixture
def relayed(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture relayed calls and serve a canned bound project."""
    calls: list = []

    def fake_relay(function_id: str, payload: dict) -> dict:
        calls.append((function_id, dict(payload)))
        if function_id == state_reader.READ_FUNCTION_ID:
            return {
                "project_slug": "acme",
                "project_id": 4,
                "has_capability": True,
                "binding": {"github_repo": "acme/app", "installation_id": "77"},
                "installation": {"status": "active"},
            }
        return {"recorded": True}

    from yoke_core.domain import control_plane_transport

    monkeypatch.setattr(control_plane_transport, "relay", fake_relay)
    return calls


class TestBindingStateRead:
    def test_it_relays_when_there_is_no_local_authority(
        self, no_local_authority, relayed,
    ) -> None:
        state = state_reader.read_github_state("acme", None)
        assert [call[0] for call in relayed] == [state_reader.READ_FUNCTION_ID]
        assert relayed[0][1] == {"project": "acme"}
        assert state.project_slug == "acme"
        assert state.project_id == 4
        assert state.has_capability is True
        assert state.binding == {
            "github_repo": "acme/app", "installation_id": "77",
        }
        assert state.installation == {"status": "active"}

    def test_a_refused_relay_raises_rather_than_reporting_no_binding(
        self, no_local_authority, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unreachable read must not look like an unbound project.

        Reporting empty state would surface as 'this project has no GitHub
        App capability' and send the operator to re-bind a healthy binding.
        """
        from yoke_contracts.api.function_call import FunctionError

        class _Refused:
            success = False
            error = FunctionError(code="boom", message="control plane refused")
            result = None

        monkeypatch.setattr(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            lambda **_kwargs: _Refused(),
        )
        with pytest.raises(RuntimeError, match="control plane refused"):
            state_reader.read_github_state("acme", None)

    def test_a_caller_supplied_connection_is_used_without_relaying(
        self, relayed, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sentinel = object()
        monkeypatch.setattr(
            state_reader,
            "read_github_state_over_connection",
            lambda conn, project: sentinel,
        )
        assert state_reader.read_github_state("acme", None, conn=object()) is sentinel
        assert relayed == []


class TestStatePayload:
    def test_the_wire_shape_round_trips(self) -> None:
        original = state_reader.ProjectGithubState(
            project_slug="acme",
            project_id=4,
            has_capability=True,
            binding={"github_repo": "acme/app"},
            installation={"status": "active"},
        )
        rebuilt = state_reader.state_from_payload(
            state_reader.state_payload(original)
        )
        assert rebuilt == original

    def test_an_unbound_project_round_trips_as_unbound(self) -> None:
        original = state_reader.empty_state("acme")
        rebuilt = state_reader.state_from_payload(
            state_reader.state_payload(original)
        )
        assert rebuilt == original
        assert rebuilt.binding is None
        assert rebuilt.installation is None


class TestSyncReceipt:
    def test_it_relays_when_there_is_no_local_authority(
        self, no_local_authority, relayed,
    ) -> None:
        receipt.register_installation_token("token-value", "acme")
        assert receipt.record_installation_token_result(
            "token-value", outcome="success",
        ) is True
        assert relayed == [(
            receipt.RECORD_FUNCTION_ID,
            {"project": "acme", "outcome": "success", "error": ""},
        )]

    def test_an_untracked_token_relays_nothing(
        self, no_local_authority, relayed,
    ) -> None:
        assert receipt.record_installation_token_result(
            "never-registered", outcome="success",
        ) is False
        assert relayed == []

    def test_a_refused_relay_reports_no_receipt_rather_than_raising(
        self, no_local_authority, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A lost receipt is metadata, not the operation — it must not raise."""
        from yoke_core.domain import control_plane_transport

        def refuse(*_args, **_kwargs):
            raise RuntimeError("control plane refused")

        monkeypatch.setattr(control_plane_transport, "relay", refuse)
        receipt.register_installation_token("token-value", "acme")
        assert receipt.record_installation_token_result(
            "token-value", outcome="failed", error="HTTPError",
        ) is False
