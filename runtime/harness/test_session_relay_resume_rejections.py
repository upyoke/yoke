"""Permanent wake rejections release custody and stay visible in health."""

from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_report_retry import retry_pending_reports
from yoke_harness.session_relay_resume_settlement import settle_finished_native_resumes
from yoke_harness.session_relay_native_capture_format import compose_capture
from runtime.harness.test_session_relay_resume_settlement import (
    ATTEMPT_ID,
    FUNCTION_ID,
    LEASE_ID,
    SESSION_ID,
)


@pytest.mark.parametrize(
    "code",
    [
        "report_conflict",
        "attempt_missing",
        "relay_lease_expired",
        "transport_error",
        "server_error",
    ],
)
def test_rejected_finished_resume_retries_only_recoverable_failures(
    tmp_path: Path, code: str, monkeypatch
) -> None:
    custody = tmp_path / "custody"
    relay = tmp_path / "relay"
    capture = tmp_path / "native.capture"
    capture.write_bytes(compose_capture(stdout=b"", stderr=b"", exit_code=0))
    record_supervised_native(
        ATTEMPT_ID,
        os.getpid(),
        native_session_id=SESSION_ID,
        supervision_kind="resume",
        capture_path=capture,
        lease_id=LEASE_ID,
        state_dir=custody,
    )
    monkeypatch.setattr(
        "yoke_harness.session_process_custody.group_members", lambda group: {}
    )
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if code == "transport_error":
            raise OSError("offline")
        return SimpleNamespace(success=False, error=SimpleNamespace(code=code))

    def settle():
        return settle_finished_native_resumes(
            dispatch,
            FUNCTION_ID,
            relay_id="machine:relay",
            machine_id=SESSION_ID,
            state_dir=relay,
            custody_state_dir=custody,
            timeout_s=5,
        )

    permanent = code in {"report_conflict", "attempt_missing", "relay_lease_expired"}
    assert settle() == ((ATTEMPT_ID,) if permanent else ())
    assert supervision_record_path(ATTEMPT_ID, custody).exists() is not permanent
    assert settle() == ()
    assert len(calls) == (1 if permanent else 2)
    assert capture.exists()
    # Draining the ordinary report queue must not erase custody rejection evidence.
    assert retry_pending_reports(dispatch, FUNCTION_ID, state_dir=relay, timeout_s=5)
    health = observe_relay_health(relay)
    if permanent:
        assert health["state"] == "quarantined"
        assert health["pending_reports"] == 0
        assert health["quarantine_count"] == 1
        assert health["quarantined_reports"][0]["error_code"] == code
    else:
        assert health["quarantine_count"] == 0
