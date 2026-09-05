"""Receipt coverage for the Test Mac reset's relay-service unload phase.

Companion to `test_ssh_mac_full_reset_relay_service.py`, which drives the
phase's shell functions directly. These tests instead exercise the Python
parser against the fake transport, the same layer `test_ssh_mac_full_reset.py`
covers for every other reset phase.
"""

from __future__ import annotations

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    closed_reset_stdout,
)
from runtime.api.domain.test_ssh_mac_full_reset import _run
from yoke_core.domain.ssh_mac_full_reset_contract import (
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)
from yoke_harness.ssh_mac_full_reset_contract import (
    RELAY_SERVICE_LABEL,
    RELAY_SERVICE_LABEL_PREFIX,
    RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED,
    RESET_RELAY_SERVICE_PREFIX,
    RESET_RELAY_SERVICE_RECOVERY,
)


def test_reset_reports_whether_a_relay_service_had_to_be_unloaded() -> None:
    transport = FakeResetTransport(closed_reset_stdout(relay_services_unloaded=1))

    result = _run(transport)

    assert result.ok
    # A host that never had a relay loaded and one whose relay was booted out
    # reach the same end state; only this count distinguishes them.
    assert result.evidence["relay_service_state"] == {
        "label": RELAY_SERVICE_LABEL,
        "instance_label_prefix": RELAY_SERVICE_LABEL_PREFIX,
        "services_unloaded": 1,
        "services_loaded": False,
    }


def test_reset_stops_before_the_wipe_when_a_relay_service_stays_loaded() -> None:
    label = f"{RELAY_SERVICE_LABEL_PREFIX}57976ddac4709032"
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["unload_relay_service"],
                RESET_RELAY_SERVICE_PREFIX
                + RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED
                + " "
                + label,
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    assert not result.ok
    assert result.error_code == "test_mac_reset_unload_relay_service_failed"
    assert result.evidence["reset_phase"] == "unload_relay_service"
    # The receipt names the exact service and how to clear it. Reporting only
    # the phase is what sent the last operator to diagnose launchd by hand
    # after a reset removed the home and failed its own absence check.
    assert result.evidence["relay_service_state"] == {
        "label": label,
        "reason": RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED,
        "recovery": RESET_RELAY_SERVICE_RECOVERY[
            RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED
        ].format(label=label),
    }
    assert label in str(result.evidence["relay_service_state"]["recovery"])


def test_reset_refuses_a_relay_failure_naming_a_service_it_does_not_own() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                RESET_FAILURE_PREFIX + RESET_PHASES["unload_relay_service"],
                RESET_RELAY_SERVICE_PREFIX
                + RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED
                + " com.vendor.somethingelse",
            )
        ),
        reset_returncode=1,
    )

    result = _run(transport)

    # The phase handles this account's Yoke relay and nothing else, so a label
    # outside that naming authority is not a receipt this parser accepts.
    assert not result.ok
    assert result.error_code == "test_mac_reset_failed"
    assert "relay_service_state" not in result.evidence
