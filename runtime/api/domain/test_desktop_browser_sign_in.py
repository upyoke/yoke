"""Native sign-in checks use native cookies and never expose them in evidence."""

import json
import subprocess
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from yoke_contracts.browser_identity import BrowserIdentity, SignInCheck
from yoke_harness import desktop_browser_sign_in as desktop


def cookie_jar():
    jar = CookieJar()
    jar.set_cookie(
        Cookie(
            0,
            "session",
            "private-cookie",
            None,
            False,
            "app.example",
            False,
            False,
            "/",
            True,
            True,
            None,
            True,
            None,
            None,
            {"HTTPOnly": ""},
        )
    )
    return jar


@pytest.fixture
def native(monkeypatch, tmp_path):
    state = {"quit": [], "requests": []}
    monkeypatch.setattr(
        desktop, "quit_browser", lambda kind: state["quit"].append(kind)
    )
    monkeypatch.setattr(desktop, "native_cookies", lambda kind: cookie_jar())
    original = httpx.Client

    def request(req):
        state["requests"].append(req)
        return httpx.Response(
            303 if req.headers.get("cookie") == "session=private-cookie" else 200
        )

    monkeypatch.setattr(
        desktop.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(request), **kw),
    )
    return state, SimpleNamespace(node=Path("node"), runtime_dir=tmp_path, env={})


@pytest.mark.parametrize("kind", ["Chromium", "Safari"])
def test_status_probe_uses_native_cookies_without_following_sign_in_redirect(
    native, kind
):
    state, runtime = native
    identity = BrowserIdentity(
        "admin",
        (
            SignInCheck(
                "app",
                "https://app.example",
                "https://app.example/auth/sign-in",
                signed_in_status=303,
                account="operator@example.com",
            ),
        ),
    )
    sites = desktop.check_desktop(identity, runtime, kind=kind)
    assert sites[0]["state"] == "signed_in"
    assert sites[0]["account"] == "operator@example.com"
    assert state["quit"] == [kind]
    assert len(state["requests"]) == 1
    assert "private-cookie" not in json.dumps(sites)


def test_selector_probe_passes_only_matching_cookies_on_private_stdin(
    native, monkeypatch
):
    _, runtime = native
    calls = []
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda argv, **kw: (
            calls.append((argv, kw))
            or subprocess.CompletedProcess(
                argv,
                0,
                '{"sites":[{"site":"app","state":"signed_in","detail":"visible"}]}',
                "",
            )
        ),
    )
    identity = BrowserIdentity(
        "admin",
        (
            SignInCheck(
                "app",
                "https://app.example",
                "https://app.example/home",
                signed_in_selector="#account",
            ),
        ),
    )
    sites = desktop.check_desktop(identity, runtime, kind="Safari")
    argv, kwargs = calls[0]
    assert "private-cookie" not in str(argv)
    assert json.loads(kwargs["input"])["cookies"][0]["value"] == "private-cookie"
    assert sites[0]["state"] == "signed_in"


@pytest.mark.parametrize("kind", ["Chromium", "Safari"])
def test_loader_uses_exact_desktop_store_and_never_logs_cookie_errors(
    tmp_path, monkeypatch, kind
):
    import browser_cookie3

    store = tmp_path / "Cookies"
    store.touch()
    monkeypatch.setattr(desktop, "cookie_file", lambda _: store)
    seen = []

    def load(**kwargs):
        seen.append(kwargs)
        raise RuntimeError("private-cookie")

    monkeypatch.setattr(
        browser_cookie3, "chromium" if kind == "Chromium" else "safari", load
    )
    with pytest.raises(
        RuntimeError, match="desktop_browser_cookie_store_unreadable"
    ) as exc:
        desktop.native_cookies(kind)
    assert "private-cookie" not in str(exc.value)
    assert seen == [{"cookie_file": str(store)}]


def test_missing_store_is_empty_without_creating_it(tmp_path, monkeypatch):
    store = tmp_path / "missing"
    monkeypatch.setattr(desktop, "cookie_file", lambda _: store)
    assert list(desktop.native_cookies("Safari")) == []
    assert not store.exists()


def test_snap_cookie_path_uses_the_desktop_last_used_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    root = tmp_path / desktop.SNAP_CHROMIUM_HOME_ENTRY
    root.mkdir(parents=True)
    (root / "Local State").write_text('{"profile":{"last_used":"Profile 1"}}')
    cookies = root / "Profile 1/Network/Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.touch()
    assert desktop.cookie_file("Chromium") == cookies


@pytest.mark.parametrize("selected", ["../other", "/outside", ".."])
def test_snap_profile_selection_cannot_escape_the_native_store(
    tmp_path, monkeypatch, selected
):
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    root = tmp_path / desktop.SNAP_CHROMIUM_HOME_ENTRY
    root.mkdir(parents=True)
    (root / "Local State").write_text(json.dumps({"profile": {"last_used": selected}}))
    with pytest.raises(RuntimeError, match="desktop_browser_profile_unreadable"):
        desktop.cookie_file("Chromium")


def test_no_declared_desktop_sites_refuses_before_quitting(native):
    state, runtime = native
    with pytest.raises(RuntimeError, match="desktop_browser_sites_undeclared"):
        desktop.check_desktop(BrowserIdentity("default"), runtime, kind="Safari")
    assert state["quit"] == []


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Safari", ["/usr/bin/open", "-a", "Safari"]),
        ("Chromium", ["/snap/bin/chromium", "--new-window"]),
    ],
)
def test_operator_window_uses_native_browser_without_automation_crypto_switches(
    native, monkeypatch, kind, expected
):
    state, _ = native
    spawned = []
    windows = iter([1, 0])
    monkeypatch.setattr(desktop, "window_count", lambda _: next(windows))
    monkeypatch.setattr(desktop.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        desktop.subprocess, "Popen", lambda argv, **kw: spawned.append(argv)
    )
    desktop.sign_in_window(kind, ["https://app.example"])
    assert spawned == [[*expected, "https://app.example"]]
    assert state["quit"] == [kind]
