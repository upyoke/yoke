"""Windows session probes refuse unreadable state before any desktop action."""

import base64
from types import SimpleNamespace

import pytest

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.windows_desktop_state import (
    SESSION_QUERY_TIMEOUT,
    active_windows_sessions,
)


@pytest.mark.parametrize(
    "stdout", ["[]", '[{"session_id": 2, "user": "Administrator"}]']
)
def test_active_windows_logins_use_native_wts_query(stdout):
    calls = []

    def run(command, **kwargs):
        script = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")
        assert (
            "WTSEnumerateSessions" in script and "WTSQuerySessionInformation" in script
        )
        assert "s.State != 0" in script
        assert kwargs["timeout"] == SESSION_QUERY_TIMEOUT
        assert SESSION_QUERY_TIMEOUT > 20  # Includes cold native module startup.
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=stdout)

    result = active_windows_sessions(SimpleNamespace(_run=run))
    assert isinstance(result, list) and len(calls) == 1


@pytest.mark.parametrize(
    "code,stdout",
    [
        (1, "[]"),
        (0, "bad"),
        (0, "{}"),
        (0, '[{"session_id": 0, "user": "Administrator"}]'),
        (0, '[{"session_id": 2}]'),
    ],
)
def test_unknown_login_state_has_named_recovery(code, stdout):
    control = SimpleNamespace(
        _run=lambda *a, **kw: SimpleNamespace(returncode=code, stdout=stdout)
    )
    with pytest.raises(
        DesktopAccessError,
        match="windows_desktop_state_unknown.*no RDP login was started",
    ):
        active_windows_sessions(control)


def test_unknown_state_preserves_bounded_redacted_probe_evidence():
    secret = "registered-desktop-secret"
    control = SimpleNamespace(
        secret_values=(secret,),
        _run=lambda *a, **kw: SimpleNamespace(
            returncode=124,
            stdout="unfinished " + secret,
            stderr="preparing modules " + secret + "x" * 2000,
        ),
    )
    with pytest.raises(DesktopAccessError) as failure:
        active_windows_sessions(control)
    detail = str(failure.value)
    assert "query exit=124" in detail and "stdout='unfinished [REDACTED]'" in detail
    assert "stderr='preparing modules [REDACTED]" in detail
    assert secret not in detail and len(detail) < 800
