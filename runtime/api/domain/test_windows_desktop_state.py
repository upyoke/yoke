"""Windows session probes refuse unreadable state before any desktop action."""

import base64
from types import SimpleNamespace

import pytest

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.windows_desktop_state import active_windows_sessions


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
        assert kwargs["timeout"] == 15
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
