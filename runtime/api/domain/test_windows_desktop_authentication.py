"""SDL auth-only disconnect needs an explicit protocol success receipt."""

import subprocess

import pytest

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.windows_desktop_session import _authenticate


@pytest.mark.parametrize(
    "status, passes",
    [
        ("ERRBASE_SUCCESS [0x00000000]", True),
        ("ERRCONNECT_AUTHENTICATION_FAILED [0x00020009]", False),
        ("", False),
    ],
)
def test_auth_only_disconnect_requires_confirmed_authentication(
    monkeypatch, status, passes
):
    password = "synthetic-private-password"

    def run(argv, **kwargs):
        assert kwargs["input"] == password + "\n"
        assert password not in repr(argv)
        return subprocess.CompletedProcess(
            argv, 1, "", "[sdl_client_thread_connect]: Authentication only, " + status
        )

    monkeypatch.setattr(subprocess, "run", run)
    if passes:
        _authenticate(["sdl-freerdp", "/log-level:OFF"], password)
    else:
        with pytest.raises(DesktopAccessError) as error:
            _authenticate(["sdl-freerdp", "/log-level:OFF"], password)
        assert password not in str(error.value)
