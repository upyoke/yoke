"""The sign-in window's cookies really do reach the daemon's browser context.

Both halves of this path failed silently in production and neither is visible
to a unit test: a cookie Chromium cannot decrypt is dropped without a word,
and a session cookie is discarded when the profile is next opened. So this
drives the real binary end to end -- a page sets a session cookie in a window
built from the real launch arguments, the window closes, and a real Playwright
persistent context on that same profile is asked what it holds.

The launch arguments come from this repository's own ``authorize.js``, while
Chromium and Playwright come from the machine's materialized runtime -- a test
that read both from the materialized copy would pass while the change under
test sat unshipped. It skips when that runtime or its Chromium is absent. The
window runs headless here only because a test machine has no display; headless
changes neither how cookies are stored nor how they are encrypted.
"""

from __future__ import annotations

import http.server
import json
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest

from yoke_cli.config.browser_profile_cookies import (
    cookie_store_path,
    keep_sign_in_cookies,
)
from yoke_harness import browser_runtime

AUTHORIZE_JS = Path(browser_runtime.__file__).parent / "src" / "authorize.js"

COOKIE_NAME = "yoke_probe_session"
COOKIE_VALUE = "signed-in"
WINDOW_TIMEOUT_SECONDS = 180
COOKIE_SETTLE_SECONDS = 3


def _runtime_dir() -> Path | None:
    runtime = Path.home() / ".yoke" / "browser-runtime"
    if not (runtime / "node_modules" / "playwright").is_dir():
        return None
    return runtime


def _node(runtime: Path, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "-e", script],
        cwd=str(runtime), capture_output=True, text=True, timeout=WINDOW_TIMEOUT_SECONDS,
    )


@pytest.fixture(scope="module")
def browser_runtime() -> Path:
    runtime = _runtime_dir()
    if runtime is None:
        pytest.skip("browser runtime is not materialized on this machine")
    try:
        resolved = _node(
            runtime,
            "process.stdout.write(require('playwright').chromium.executablePath())",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"node is not usable here: {exc}")
    if resolved.returncode != 0 or not Path(resolved.stdout.strip()).exists():
        pytest.skip("Playwright's Chromium is not installed on this machine")
    return runtime


class _SessionCookieHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - the stdlib server's own method name
        self.server.hits.append(self.path)
        body = b"<html><body>yoke sign-in probe</body></html>"
        self.send_response(200)
        # No Max-Age and no Expires: exactly the shape a hosted app's session
        # cookie has, and the shape Chromium throws away on the next launch.
        self.send_header("Set-Cookie", f"{COOKIE_NAME}={COOKIE_VALUE}; Path=/")
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture()
def probe_server():
    # Threaded, not serial: Chromium opens speculative connections before it
    # sends anything on them, and a single-threaded server blocks in the
    # handler for one of those while the real request waits behind it.
    with http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _SessionCookieHandler,
    ) as server:
        # The served requests are the proof that the window reached the page;
        # without them, "no cookie" cannot be told apart from "no page load".
        server.hits = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()


def _stored_cookies(profile: Path) -> list[tuple]:
    store = cookie_store_path(profile)
    if not store.is_file():
        return []
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT name, is_persistent FROM cookies WHERE name = ?", (COOKIE_NAME,),
        ).fetchall()
    finally:
        connection.close()


def _sign_in_window(runtime: Path, profile: Path, probe) -> None:
    """Run the real launch arguments, then close the window as an operator does.

    The window is closed once the page has actually been served, and the cookie
    store is read only afterwards, because Chromium writes cookies to the
    profile in batches and flushes what is pending when it shuts down. Polling
    the store while the browser is still up measures that batch timer instead
    of the behaviour under test.

    The browser's own stderr is kept and reported, because a window that never
    reaches the page is otherwise indistinguishable from one that never
    started -- and this test shares a machine with the rest of the suite, so
    "it was slow" and "it failed to launch" are both live possibilities.
    """
    url = f"http://127.0.0.1:{probe.server_address[1]}/"
    built = _node(
        runtime,
        f"process.stdout.write(JSON.stringify(require({json.dumps(str(AUTHORIZE_JS))})"
        f".buildLaunchArgs({json.dumps({'profileDir': str(profile), 'url': url})})))",
    )
    assert built.returncode == 0, built.stderr
    args = json.loads(built.stdout)
    executable = _node(
        runtime, "process.stdout.write(require('playwright').chromium.executablePath())",
    ).stdout.strip()
    browser_log = profile.parent / "browser-stderr.log"
    with open(browser_log, "w", encoding="utf-8") as stderr_log:
        window = subprocess.Popen(
            [executable, "--headless=new", *args],
            stdout=subprocess.DEVNULL, stderr=stderr_log,
        )
    try:
        deadline = time.monotonic() + WINDOW_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not probe.hits:
            if window.poll() is not None:
                break
            time.sleep(0.5)
        assert probe.hits, (
            "the window never reached the probe page "
            f"(exit={window.poll()}, waited={WINDOW_TIMEOUT_SECONDS}s, url={url}); "
            f"browser stderr tail: "
            f"{browser_log.read_text(encoding='utf-8', errors='replace')[-2000:]!r}"
        )
        # The response is served before the renderer has stored its cookie;
        # give that hop a moment so the shutdown below has it to flush.
        time.sleep(COOKIE_SETTLE_SECONDS)
    finally:
        window.terminate()
        try:
            window.wait(timeout=30)
        except subprocess.TimeoutExpired:
            window.kill()
            window.wait()


def _daemon_context_cookies(runtime: Path, profile: Path) -> list[str]:
    """Ask a real Playwright persistent context what the profile holds."""
    read = _node(
        runtime,
        "const { chromium } = require('playwright');"
        f"chromium.launchPersistentContext({json.dumps(str(profile))}, "
        "{ headless: true }).then(async (context) => {"
        "  const cookies = await context.cookies();"
        "  await context.close();"
        "  process.stdout.write(JSON.stringify(cookies.map((c) => c.name)));"
        "});",
    )
    assert read.returncode == 0, read.stderr
    return json.loads(read.stdout)


def test_a_sign_in_reaches_the_daemons_browser_context(
    browser_runtime, probe_server, tmp_path,
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()

    _sign_in_window(browser_runtime, profile, probe_server)
    assert _stored_cookies(profile) == [(COOKIE_NAME, 0)], (
        "the closed window leaves the app's cookie as a session cookie"
    )

    assert keep_sign_in_cookies(profile) == 1
    assert _daemon_context_cookies(browser_runtime, profile) == [COOKIE_NAME]
    assert _daemon_context_cookies(browser_runtime, profile) == [COOKIE_NAME], (
        "and it survives every later context, not just the first"
    )
