"""Windows plan-limit credentials stay local and probes preserve their budget."""

import base64
import json
from types import SimpleNamespace

from yoke_harness import session_relay_cursor_windows_credential as windows_credential
from yoke_harness import session_relay_plan_limits as limits
import pytest
pytestmark = pytest.mark.windows

def test_windows_claude_reads_user_credentials_without_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setattr(limits.Path, "home", lambda: tmp_path)
    credentials = tmp_path / ".claude" / ".credentials.json"
    credentials.parent.mkdir()
    credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "local-token"}}))
    monkeypatch.setattr(limits.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no keychain")))
    assert limits._load_claude_credentials()["claudeAiOauth"]["accessToken"] == "local-token"


def _cursor_profile(tmp_path, monkeypatch, dpapi_blob: bytes) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "linux"))
    monkeypatch.delenv("CURSOR_CLI_WINDOWS_CREDENTIAL_MANAGER", raising=False)
    profile = tmp_path / "roaming" / "cursor"
    profile.mkdir(parents=True)
    (profile / "auth.json").write_text(json.dumps({"storedIn": "os-secret-store"}))
    encoded = base64.b64encode(dpapi_blob).decode()
    (profile / "auth.dpapi").write_text(json.dumps({"version": 1, "dpapi": encoded}))


def test_windows_cursor_dpapi_token_reaches_only_usage_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    _cursor_profile(tmp_path, monkeypatch, b"sealed")
    payload = json.dumps({"accessToken": "dpapi-token"}).encode()
    monkeypatch.setattr(
        windows_credential, "dpapi_unprotect", lambda blob: payload if blob == b"sealed" else None
    )
    monkeypatch.setattr(limits.subprocess, "run", lambda *a, **k: pytest.fail("no subprocess"))
    sent = []

    def http(url, **kwargs):
        sent.append((url.rsplit("/", 1)[-1], kwargs["headers"]["Authorization"]))
        if url.endswith("GetHardLimit"):
            return {"noUsageBasedAllowed": True}
        if url.endswith("GetPlanInfo"):
            return {"planInfo": {"planName": "Pro"}}
        return {"planUsage": {"autoPercentUsed": 10, "apiPercentUsed": 20}}

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    reading = limits.probe_cursor_cli(observed_at="2026-11-22T12:00:00Z")
    assert sent == [
        (name, "Bearer dpapi-token")
        for name in ("GetPlanInfo", "GetCurrentPeriodUsage", "GetHardLimit")
    ]
    assert [w["status"] for w in reading["windows"]] == ["ok", "ok"]
    assert "dpapi-token" not in repr(reading)


def test_windows_cursor_missing_store_reason_reaches_the_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    _cursor_profile(tmp_path, monkeypatch, b"sealed")
    (tmp_path / "roaming" / "cursor" / "auth.dpapi").unlink()
    monkeypatch.setattr(limits, "plan_limit_http_json", lambda *a, **k: pytest.fail("no request"))
    reading = limits.probe_cursor_cli(observed_at="2026-11-22T12:00:00Z")
    assert reading["windows"][0]["reason"] == "cursor_secret_store_missing"


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    sealed = Blob()
    assert crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(sealed)
    ), ctypes.get_last_error()
    try:
        return ctypes.string_at(sealed.pbData, sealed.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(sealed.pbData, ctypes.c_void_p))


@pytest.mark.windows_only(reason="exercises the real per-user DPAPI boundary")
def test_windows_dpapi_round_trip_with_a_test_user_fixture(tmp_path, monkeypatch):
    payload = json.dumps({"accessToken": "fixture-token"}).encode()
    _cursor_profile(tmp_path, monkeypatch, _dpapi_protect(payload))
    assert windows_credential.cursor_windows_access_token() == ("fixture-token", "")
    _cursor_profile(tmp_path / "corrupt", monkeypatch, b"not a dpapi blob")
    assert windows_credential.cursor_windows_access_token() == (
        None,
        "cursor_secret_store_missing",
    )


def test_windows_claude_usage_sends_local_token_only_to_usage_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setattr(limits, "_load_claude_credentials", lambda: {"claudeAiOauth": {"accessToken": "local-token"}})
    monkeypatch.setattr(limits, "probe_cli_surface", lambda *a, **k: SimpleNamespace(verdict="ok", version="2.3.4"))
    sent = []
    monkeypatch.setattr(limits, "plan_limit_http_json", lambda url, **kw: sent.append(kw) or "http_timeout")
    reading = limits.probe_claude_cli(observed_at="2026-11-16T12:00:00Z")
    assert sent[0]["headers"]["Authorization"] == "Bearer local-token"
    assert "local-token" not in repr(reading)
    assert "http_timeout" in repr(reading)
