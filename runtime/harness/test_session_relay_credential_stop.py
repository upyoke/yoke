"""A refused claim never spins: a dead credential stops, anything else backs off."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from yoke_contracts.https_retry_policy import TERMINAL_AUTHENTICATION_CODES
from yoke_harness import session_relay
from yoke_harness.session_relay_daemon import poll_backoff_seconds, serve_forever
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_poll_health import poll_connection_recovery
from yoke_harness.session_relay_schedule import RELAY_NEXT_POLL_FILE_NAME


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        project_ids=(10,),
        surface_versions={},
    )


def _refusing_claims(code: str, claims: list[str]):
    def dispatch(**kwargs):
        if kwargs["function_id"] != session_relay.RELAY_CLAIM_FUNCTION_ID:
            return SimpleNamespace(success=True, result={})
        claims.append(code)
        return SimpleNamespace(success=False, error=SimpleNamespace(code=code))

    return dispatch


@pytest.mark.parametrize("code", sorted(TERMINAL_AUTHENTICATION_CODES))
def test_rejected_credential_stops_the_relay_and_status_teaches_reconnect(
    tmp_path, code
) -> None:
    claims: list[str] = []

    outcome = serve_forever(
        state_dir=tmp_path,
        stop_after_cycles=5,
        idle_tick_seconds=0,
        install_signals=False,
        inventory_provider=_inventory,
        dispatcher=_refusing_claims(code, claims),
    )

    assert outcome.reason == session_relay.CREDENTIAL_REJECTED
    assert claims == [code]
    health = observe_relay_health(tmp_path)
    assert health["poll_outcome"]["error_code"] == code
    assert "`yoke connect`, then `yoke relay install`" in poll_connection_recovery(
        health
    )


def test_refused_claim_backs_off_instead_of_polling_every_idle_tick(
    tmp_path,
) -> None:
    claims: list[str] = []
    started = time.time()

    outcome = serve_forever(
        state_dir=tmp_path,
        stop_after_cycles=5,
        idle_tick_seconds=0,
        install_signals=False,
        inventory_provider=_inventory,
        dispatcher=_refusing_claims("unexpected_field", claims),
    )

    assert outcome.last_state == "backoff"
    assert claims == ["unexpected_field"]
    due_at = float((tmp_path / RELAY_NEXT_POLL_FILE_NAME).read_text())
    assert due_at >= started + 2
    assert 2 <= poll_backoff_seconds(1) <= 5
    assert 150 <= poll_backoff_seconds(1_000) <= 300
