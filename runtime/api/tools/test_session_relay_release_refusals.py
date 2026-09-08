"""Every reason a relay cannot learn its served release is named, not blank.

The install that fails here is the one an operator retries by hand a minute
later, so the refusal it leaves behind is the only record of what differed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RelayReleaseError,
    relay_release_status,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release


def test_handshake_failure_is_named_and_records_recovery(tmp_path: Path) -> None:
    instance = relay_instance(tmp_path)

    def fail_handshake(_environment: str):
        raise TimeoutError("manifest timed out")

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(instance=instance, fetch_manifest=fail_handshake)

    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert "handshake failed" in str(raised.value)
    assert "relay install" in str(raised.value)
    observed = relay_release_status(instance=instance, refresh_served=False)
    assert observed.error_code == RELAY_RELEASE_FETCH_FAILED


def test_an_unresolved_connection_names_what_the_absent_manifest_means(
    tmp_path: Path,
) -> None:
    """The manifest reader answers ``None`` for causes it does not carry."""
    instance = relay_instance(tmp_path)

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(instance=instance, fetch_manifest=lambda _environment: None)

    message = str(raised.value)
    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert "returned no manifest" in message
    assert "https connection did not resolve, or the handshake failed" in message
    assert "yoke --env prod status" in message
    assert "yoke --env prod relay install" in message
